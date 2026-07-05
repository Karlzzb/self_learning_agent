"""教学图的共享状态 schema(``TeachState``)。

ADR-0001 把智能体建成「结构化教学流水线图」:节点按教学**能力**粗粒度拆分,
彼此通过这张共享状态通信。ADR-0003 把状态分三层——本 schema 是 **A 层
(会话/图状态)**,由 checkpointer 持久化;B/C 层(长期记忆与产物)是工作区
文件,节点在会话开始读入、会话结束写出,**不**镜像进这里以免双写不一致。

字段含义:
- ``messages``:对话历史,用 LangGraph 标准 ``add_messages`` reducer 累加。
- ``user_id`` / ``topic`` / ``topic_slug``:多租户键,定位工作区与 thread。
  首轮由输入带入并落进状态;后续轮次(尤其 resume)直接复用状态里的值。
- ``intent``:Router 的意图分类结果(后续切片据此路由到不同能力节点)。
- ``baseline_files``:会话开始时的工作区文件快照,供结束时算「本轮新产物」。
- ``new_artifacts``:本轮新产出/改动的产物相对路径,回复里据此给出产物引用。
- ``next_lesson_scope``:ZPD 节点算出的「下一课范围」(单一、紧凑、紧扣 Mission),
  供同一轮内的 Lesson 创作子图(#007)消费。它是 ZPD→Lesson 的**轮内交接量**,
  属 A 层会话状态(checkpointer 持久化),**不**落成 B/C 层产物文件——避免与
  课程 HTML 等真正产物双写(ADR-0003:文件是 B/C 的单一事实源,这里只是规划中间态)。
- ``last_lesson``:Lesson 节点产出后交给同一轮内 Reference 节点(#009)的**轮内交接量**
  ——``{committed, scope, summary, lang}``。Reference 节点据 ``committed`` 决定是否把刚
  写好的课程压缩成参考文档(暂缓的课不产参考)。同 ``next_lesson_scope``,是 A 层规划
  中间态,不落 B/C 产物文件。
- ``workspace_language``:Workspace Language 码(#020 / ADR-0013),会话开始由
  ``load_workspace`` 从工作区元文件读入并透出到状态,下游生成节点与确定性渲染器读它
  (``<html lang>`` / chrome 文案 / 内容语言)而**不逐节点重猜**。它是 B 层工作区事实
  (``workspace.json``,单一事实源)的会话内镜像:纯读取透出,不在此双写落盘;Mission
  establish 在同一轮内检测并持久化该事实时,也把码写回本字段,使同轮级联的 zpd/lesson/
  reference 立即读到(此时 ``load_workspace`` 早已跑过,元文件尚不存在)。
- ``spawn_topic``:new_topic 交接信号(#014 / §D4)。学习者请求领域外新主题、经确认后,
  new_topic 节点把新主题名写入此字段并路由 finalize(**不**在旧 workspace 写任何文件);
  ``runner.invoke_turn`` 把它透出 ``TurnResult``,由 driver(cli/api)用新 ``topic`` 另起
  一次 invoke(新 thread / 新记忆目录)。是一次性交接量,不落 B/C 产物文件。
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from .sanitize import sanitize_surrogates


class CapturedNote(BaseModel):
    """一条被节点捕捉到的 Learner Note(ADR-0012 三层记忆之第三层)。

    这是**跨节点共享的 LLM 结构化输出形状**:Mission 与 Assessment 节点在捕捉到学习者的
    偏好 / 节奏 / 反复卡点 / 未解决疑问 / 系统背景时,让模型以此形状报出;节点再把它翻译成
    确定性原语的输入 ``workspace.LearnerNote`` 落盘(何时写=教学判断,怎么写=确定性原语)。
    定义在此(而非各节点内)以保证"模型怎么报"的类别集单一事实源;``category`` 的 Literal
    必须与 ``workspace._NOTE_CATEGORIES`` 的键一致(后者以静默丢弃未知类别兜底防漂移)。
    "学习者哪些有疑问"落在 ``open_question``,而**不**作为 Learning Record 的第五类证据(ADR-0012)。
    """

    category: Literal[
        "preference", "pace", "sticking_point", "open_question", "background"
    ] = Field(
        description=(
            "Which kind of learner note: 'preference' (how they want to be taught), "
            "'pace' (their learning speed/rhythm), 'sticking_point' (something they "
            "repeatedly struggle with), 'open_question' (an unresolved question to "
            "return to), or 'background' (OS, installed tools, profession, environment)."
        )
    )
    text: str = Field(
        description="The note itself, one concise sentence in the learner's language."
    )


def _sanitizing_add_messages(left, right):
    """``add_messages`` 的清洗包装:合并后把任何字符串消息内容里的孤立代理项替换成
    U+FFFD(见 ``sanitize.py``)。

    这是「消息进入 A 层会话状态」这个系统边界的确定性护栏。节点产出的 ``AIMessage``
    回复可能夹带上游模型吐出的孤立 UTF-8 代理项;若原样入状态,一来会被 checkpointer
    持久化,二来会在后续轮次随 transcript(``mission``/``assessment``/``wisdom`` 节点都把
    完整 ``messages`` 发回模型)进请求体,strict UTF-8 编码时抛 ``UnicodeEncodeError``。
    在此统一清洗,坏字节既不进历史、也不会再发回 API。清洗幂等,已干净的历史不受影响。
    """
    merged = add_messages(left, right)
    for message in merged:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            cleaned = sanitize_surrogates(content)
            if cleaned != content:
                message.content = cleaned
    return merged


class TeachState(TypedDict, total=False):
    """教学图的会话/图状态(A 层,checkpointer 持久化)。"""

    messages: Annotated[list[AnyMessage], _sanitizing_add_messages]
    user_id: str
    topic: str
    topic_slug: str
    intent: str
    baseline_files: dict[str, float]
    new_artifacts: list[str]
    next_lesson_scope: dict
    last_lesson: dict
    workspace_language: str
    spawn_topic: str
