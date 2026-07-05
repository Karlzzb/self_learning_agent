"""教学图:Router 分流 → Mission / Research / ZPD / Assessment → Lesson → finalize。

拓扑(S7 在 ZPD/规划与 Lesson 创作之上长出对话式评估能力,承接 ADR-0001/0002;
#013/ADR-0010 把 ``mission``、``research`` 的出边改成**条件边**,让一个 Turn 内
自动级联走完 teach 路径,直到交付第一课或必须停下问学习者):

    START → load_workspace → router → {mission | research | zpd | assessment | wisdom} → finalize → END
                                       mission →(teach:research|zpd)  research →(zpd|finalize)
                                                       zpd → lesson → reference → finalize

- ``load_workspace``:把工作区当前文件扫成基线快照(会话开始读入文件)。
- ``router``:意图分类。**确定性优先**——``MISSION.md`` 未填充时直接路由到
  Mission 节点的 establish 模式(无需 LLM);使命已立时才用轻档 LLM 判定
  「想改使命(mission_change)还是继续学(teach)」。
- ``mission``:Mission 能力节点(见 ``mission.py``)。establish:访谈学习者的
  WHY 并写出 ``MISSION.md``;change:确认后更新 ``MISSION.md`` + 追加学习记录。
- ``research``:Research 能力节点(见 ``research.py``)。teach 路径上、当
  ``RESOURCES.md`` 尚未充实时先采集高信任资源——忠实承接 SKILL.md §Philosophy
  「Before the RESOURCES.md is well-populated, your focus should be to find
  high-quality resources」。这一步是**确定性路由**(无需 LLM):RESOURCES.md
  缺失即先 research。
- ``zpd``:ZPD/规划能力节点(见 ``zpd.py``)。使命已立、资源已备、学习者想继续学
  时,读 ``learning-records`` + ``MISSION.md`` 选出**单一、紧凑、紧扣 mission**的
  下一课范围,写入图状态 ``next_lesson_scope``(忠实承接 SKILL.md §ZPD)。
- ``lesson``:**Lesson 创作能力节点**(见 ``lesson.py`` / ADR-0006 / #007)。消费 ZPD
  选出的 ``next_lesson_scope``,跑创作子图(起草 → 机器校验 → 自审 → 不达标则重写)
  产出一节通过质量门的课程 HTML;重试耗尽则不交付、请学习者稍后再来(状态不丢)。
- ``reference``:**Reference 能力节点**(见 ``reference.py`` / P5 / #009)。紧跟 Lesson:
  课程已交付时把它压缩成可快速查阅的参考文档(课程的耐用对应物),落盘 + 维护参考索引;
  课程暂缓则空操作。忠实承接 SKILL.md §Reference Documents「While creating lessons, you
  should also create reference documents」。
- ``assessment``:**对话式评估能力节点**(见 ``assessment.py`` / ADR-0002 ii / #008)。
  学习者做完课回来反思/作答/讨论时,评估其理解、追问误解,并据 P6 证据纪律决定是否
  追加一条学习记录(纯「覆盖过」不写)——记录回流影响下一轮 ZPD 选课。
- ``wisdom``:**Wisdom 能力节点**(见 ``wisdom.py`` / P4 / #010)。学习者提出需要实战智慧的
  问题时,先据已 curate 知识尝试回答,再把学习者引导到高声望社区(从 search 候选甄别),
  并把社区 / opt-out 偏好增量 upsert 进 RESOURCES.md 的 Wisdom 段。忠实承接 SKILL.md
  §Acquiring Wisdom「attempt to answer - but to ultimately delegate to a community」。
- ``finalize``:对比基线与当前快照,算出本轮新产物 → ``new_artifacts``。

checkpointer 可注入:默认 SQLite(MVP),测试传 ``MemorySaver`` 保持离线确定性。
所有触网都收敛在 ``models.get_model``(Router/Mission 的 LLM 调用),图层缝测试
通过注入 fake model 保持 hermetic。
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Literal

from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from . import config, models, prompts, workspace
from .assessment import assessment_node
from .lesson import lesson_node
from .mission import mission_node
from .new_topic import new_topic_node
from .reference import reference_node
from .research import research_node
from .state import TeachState
from .tenancy import topic_slug
from .wisdom import wisdom_node
from .workspace import workspace_dir
from .zpd import zpd_node


def _last_human_text(messages: list[AnyMessage]) -> str:
    """取最近一条人类消息文本(Router/能力节点据此工作)。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


# --- Router 的意图分类 schema -------------------------------------------------
class _RouterIntent(BaseModel):
    """使命已立时,对学习者最新一条消息的意图分类。"""

    intent: Literal["mission_change", "new_topic", "assess", "wisdom", "teach"] = Field(
        description=(
            "'mission_change' if they want to change why they learn the SAME subject; "
            "'new_topic' if they want to learn a DIFFERENT subject/domain than the current "
            "mission (a whole new area, not the next step within this mission); "
            "'assess' if they are reflecting on / answering about / discussing what they "
            "have been learning (reporting how they did, explaining a concept back, or "
            "revealing what they know or believe); "
            "'wisdom' if they are asking a real-world judgement / practitioner-experience "
            "question (how it plays out in practice, what to do in a real situation) rather "
            "than asking to be taught a new concept; else 'teach'."
        )
    )


# --- 节点 ---------------------------------------------------------------------
def load_workspace(state: TeachState) -> dict:
    """会话开始:确保工作区存在,扫描文件作基线快照(供算本轮新产物),并读入
    持久化的 Workspace Language 透出到状态(#020 / ADR-0013),供下游节点与渲染器读它
    而非逐节点重猜。未持久化(全新工作区 / 尚未确立 Mission)则不置该字段,下游回退
    默认语言;Mission establish 会在同一轮内检测并写回该字段(见 ``mission.py``)。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    workspace.ensure_workspace(directory)
    update: dict = {"baseline_files": workspace.scan_files(directory)}
    language = workspace.read_workspace_language(directory)
    if language:
        update["workspace_language"] = language
    return update


def router(state: TeachState) -> dict:
    """意图分类:确定性优先,使命已立时才用轻档 LLM 判定改/学。

    - ``MISSION.md`` 缺失 → ``mission_establish``(确定性,无需 LLM):忠实承接
      「If the MISSION.md is not populated, your first job should be to question
      the user」(SKILL.md 第 75 行)。
    - 使命已立 → 用 ``models.get_model("router")`` 判定 ``mission_change`` vs
      ``teach``。temperature=0 让分类稳定(承接「模型是可换旋钮」,逻辑不动)。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    if not workspace.exists(directory, "MISSION.md"):
        return {"intent": "mission_establish"}

    old_mission = workspace.read_text(directory, "MISSION.md") or ""
    last_human = _last_human_text(state.get("messages", []))
    result: _RouterIntent = models.get_model(
        "router", temperature=0.0
    ).with_structured_output(_RouterIntent).invoke(
        [SystemMessage(prompts.router_intent_system(old_mission)), HumanMessage(last_human)]
    )
    return {"intent": result.intent}


def _route(state: TeachState) -> str:
    """Router 出边:Mission 两种模式 → ``mission``;``assess`` → ``assessment``;teach
    路径据 RESOURCES.md 是否已备分流到 ``research``(未备,先采集资源)或 ``zpd``
    (已备,先规划下一课)。

    teach → research 是**确定性路由**(无需 LLM),忠实承接 SKILL.md §Philosophy:
    RESOURCES.md 充实之前,首要任务是找高质量资源。资源已备后进 ``zpd`` 选下一课
    范围,再由 ``zpd → lesson`` 把范围交给 Lesson 创作子图(承接 §ZPD 在创作之前)。
    ``assess`` 路径(学习者做完课回来反思/作答)进 Assessment 节点对话式评估并据证据
    写学习记录(ADR-0002 ii / #008),不直接再产新课。
    """
    if state.get("intent") in ("mission_establish", "mission_change"):
        return "mission"
    if state.get("intent") == "new_topic":
        return "new_topic"
    if state.get("intent") == "assess":
        return "assessment"
    if state.get("intent") == "wisdom":
        return "wisdom"
    return _teach_target(workspace_dir(state["user_id"], state["topic_slug"]))


def _teach_target(directory) -> str:
    """teach 路径的确定性分流:``RESOURCES.md`` 未备 → ``research``(先采集资源);
    已备 → ``zpd``(规划下一课)。Router 出边与 Mission 级联出边共用此判断,避免两处
    「先 research 再 zpd」逻辑漂移。忠实承接 SKILL.md §Philosophy。
    """
    if not workspace.exists(directory, "RESOURCES.md"):
        return "research"
    return "zpd"


def _route_after_mission(state: TeachState) -> str:
    """Mission 出边(#013/ADR-0010):单 Turn 内自动级联 teach 路径 vs 停在 finalize。

    - ``mission_establish`` 且 ``MISSION.md`` 已写成 → 继续 teach 路径(据 RESOURCES.md
      有无分流到 ``research`` 或 ``zpd``),让学习者答完使命访谈后在同一轮直接拿到第一课。
    - ``mission_change``(确认后更新 / 或声明保留)→ ``finalize``:变更使命不产课
      (承接 P3;一轮一课的间隔/交错设计)。
    - 仍在访谈中 → 节点在 ``interrupt()`` 处暂停,本出边根本不会被求值(LangGraph
      只在节点跑完后才走出边),故「无未决 interrupt」由执行模型天然保证;这里
      对 ``MISSION.md`` 是否写成再做一次确定性兜底判断。
    """
    if state.get("intent") != "mission_establish":
        return "finalize"
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    if not workspace.exists(directory, "MISSION.md"):
        return "finalize"
    return _teach_target(directory)


def _route_after_research(state: TeachState) -> str:
    """Research 出边(#013/ADR-0010):成功写出 ``RESOURCES.md`` → ``zpd`` 继续级联到
    第一课;诚实暂缓(未找到可信源、未写 RESOURCES.md)→ ``finalize`` 停在坦白告知,
    不硬塞一节没有依据的课(P1 / ADR-0009 失败姿态)。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    if workspace.exists(directory, "RESOURCES.md"):
        return "zpd"
    return "finalize"


def finalize(state: TeachState) -> dict:
    """会话结束:对比基线与当前快照,得出本轮新产物。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    current = workspace.scan_files(directory)
    return {"new_artifacts": workspace.diff_new(state.get("baseline_files", {}), current)}


# --- 装配 ---------------------------------------------------------------------
def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """装配并编译教学图。``checkpointer`` 可注入(测试传 MemorySaver)。"""
    if checkpointer is None:
        checkpointer = _default_checkpointer()

    builder = StateGraph(TeachState)
    builder.add_node("load_workspace", load_workspace)
    builder.add_node("router", router)
    builder.add_node("mission", mission_node)
    builder.add_node("research", research_node)
    builder.add_node("zpd", zpd_node)
    builder.add_node("lesson", lesson_node)
    builder.add_node("reference", reference_node)
    builder.add_node("assessment", assessment_node)
    builder.add_node("wisdom", wisdom_node)
    builder.add_node("new_topic", new_topic_node)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "load_workspace")
    builder.add_edge("load_workspace", "router")
    builder.add_conditional_edges(
        "router",
        _route,
        {
            "mission": "mission",
            "research": "research",
            "zpd": "zpd",
            "assessment": "assessment",
            "wisdom": "wisdom",
            "new_topic": "new_topic",
        },
    )
    builder.add_conditional_edges(
        "mission",
        _route_after_mission,
        {"research": "research", "zpd": "zpd", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "research",
        _route_after_research,
        {"zpd": "zpd", "finalize": "finalize"},
    )
    builder.add_edge("zpd", "lesson")
    builder.add_edge("lesson", "reference")
    builder.add_edge("reference", "finalize")
    builder.add_edge("assessment", "finalize")
    builder.add_edge("wisdom", "finalize")
    # new_topic(#014):确认后写 spawn_topic 直接 finalize;交接由 driver 用新 topic 续调。
    builder.add_edge("new_topic", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


def _default_checkpointer() -> SqliteSaver:
    """默认 SQLite checkpointer(MVP)。生产换 Postgres 只改这里。"""
    db_path = Path(config.CHECKPOINT_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(connection)


@lru_cache(maxsize=1)
def get_graph():
    """进程级单例图(CLI/runner 复用)。测试请直接调 ``build_graph(MemorySaver())``。"""
    return build_graph()


__all__ = ["build_graph", "get_graph", "topic_slug"]
