"""new_topic 节点:识别领域外新主题,确认后由 driver 代理交接(#014 / §D3-D4)。

学习者在一个 topic 学习途中,提出学一个**当前 mission 领域之外**的新东西(例如学
opencv 途中说「教我 Rust」)。router 判为 ``new_topic`` 后进入本节点:

- **确认**(承接 mission_change 的「变更前先确认」纪律):先提取新主题名,再 ``interrupt()``
  与学习者确认「要不要为它单独建一个学习档案」。
- **交接信号**:确认 → 把新主题名写入图状态 ``spawn_topic``,路由到 finalize,**不**在
  旧 workspace 写任何文件;``runner.invoke_turn`` 把 ``spawn_topic`` 透出 ``TurnResult``,
  由 driver(cli/api)用新 ``topic`` 另起一次 invoke —— 新 ``thread_id`` / 新记忆目录,
  一主题一线程不被污染(承接 ADR-0004 / ADR-0011)。
- 拒绝 → 不建档、不写文件,回到当前主题。

控制流承接 ADR-0001 的 interrupt 重跑纪律:``interrupt()`` 之前的模型决策(提取主题名)
用 ``temperature=0``,保证 resume 从头重跑时产出一致(否则 interrupt 索引会错位)。
本节点**不**写任何工作区产物——交接留在 driver 层,agent 不自管会话(ADR-0004)。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from . import language, models, prompts
from .mission import Confirmation  # 复用「是否确认」schema(与 mission_change 同一判定形状)
from .state import TeachState

# new_topic 节点所有「interrupt 之前」的决策用确定性温度(理由见模块 docstring)。
_DETERMINISTIC = 0.0


class NewTopicName(BaseModel):
    """从学习者消息里提取出的新主题名(用于确认 + 交接)。"""

    topic: str = Field(description="A short, clean name for the new subject to learn.")


def new_topic_node(state: TeachState) -> dict:
    """new_topic 能力节点:提取新主题名 → 确认 → 交接 ``spawn_topic`` 或拒绝。"""
    transcript: list[AnyMessage] = list(state.get("messages", []))
    last_human = _last_human_text(transcript)
    # 当前工作区语言(#021):确认问题 / 交接回复随持久化语言,不再硬编中文。缺失回退默认语言。
    chrome = language.chrome(state.get("workspace_language") or language.DEFAULT_LANGUAGE)
    name: NewTopicName = models.get_model(
        "router", temperature=_DETERMINISTIC
    ).with_structured_output(NewTopicName).invoke(
        [SystemMessage(prompts.new_topic_extract_system()), HumanMessage(last_human)]
    )
    topic_name = (name.topic or "").strip() or last_human.strip()

    # 2) 确认(SKILL 的「变更/新建前先确认」纪律)。问题是确定性 f-string(temp=0 提取 →
    #    跨重跑同一主题名 → 同一道问题),故 resume 重跑不会让 interrupt 索引错位。
    answer = interrupt(
        {
            "kind": "new_topic_confirm",
            "question": chrome["new_topic_confirm_question"].format(topic=topic_name),
        }
    )

    # 3) 判定是否确认(interrupt 之后,只跑一次)。未确认 → 不建档、不写任何文件。
    confirmation: Confirmation = models.get_model(
        "router", temperature=_DETERMINISTIC
    ).with_structured_output(Confirmation).invoke(
        [
            SystemMessage(prompts.new_topic_confirm_classify_system()),
            HumanMessage(str(answer)),
        ]
    )
    if not confirmation.confirmed:
        return {"messages": [AIMessage(chrome["new_topic_decline_reply"])]}

    # 4) 确认:写交接信号 spawn_topic,路由 finalize;不在旧 workspace 写任何文件。
    return {
        "spawn_topic": topic_name,
        "messages": [AIMessage(chrome["new_topic_accept_reply"].format(topic=topic_name))],
    }


def _last_human_text(messages: list[AnyMessage]) -> str:
    """取最近一条人类消息文本。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


__all__ = ["new_topic_node", "NewTopicName"]
