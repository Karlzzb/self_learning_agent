"""薄驱动层:把一条学习者消息变成一次图调用,返回回复 + 本轮产物。

ADR-0004:CLI 与(未来的)API 是同一张图的两个**薄驱动器**;本模块是它们共享
的内核。ADR-0001 的控制流在此落实:

- 每条学习者消息调用一次图,以 ``thread_id = f(user_id, topic_slug)`` 为键。
- 调用前查 checkpointer:**若有未决 interrupt → 直接 resume**(把这条消息当作
  对中断提问的回答),**否则才让 Router 做意图分类**(走正常输入)。
- 学习者离开数天 = 无调用,状态静躺 checkpointer,无需常驻进程。

返回 ``TurnResult``:学习者可见回复、本轮新产物引用、是否在等待学习者继续作答。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from .graph import get_graph
from .observability import get_callbacks
from .tenancy import thread_id, topic_slug


@dataclass(frozen=True)
class TurnResult:
    """一轮交互的外部可见结果。"""

    reply: str
    new_artifacts: list[str] = field(default_factory=list)
    awaiting_input: bool = False
    # new_topic 交接信号(#014 / §D4):非空时,driver 应立即用此新 topic 另起一次
    # invoke_turn(新 thread / 新记忆),把学习者续到新主题的 mission 访谈。
    spawn_topic: str | None = None


def _config_for(user_id: str, topic_slug_value: str) -> dict:
    # callbacks 是可观测缝的唯一接线点(ADR-0016):Langfuse 走 LangChain 回调,
    # 需在每次 graph.invoke 显式传入;关闭 tracing 时为空列表(无害 no-op)。
    return {
        "configurable": {"thread_id": thread_id(user_id, topic_slug_value)},
        "callbacks": get_callbacks(),
    }


def _has_pending_interrupt(graph, config: dict) -> bool:
    """该 thread 是否停在一个未决 interrupt 上(决定 resume vs 重新分类)。"""
    snapshot = graph.get_state(config)
    return bool(getattr(snapshot, "interrupts", ()))


def _interpret(result: dict) -> TurnResult:
    """把图返回的状态解读成 TurnResult。"""
    interrupts = result.get("__interrupt__")
    if interrupts:
        # 图停在 interrupt 上:回复就是那道提问,等待学习者作答(产物本轮尚未结算)。
        payload = interrupts[0].value
        question = payload.get("question") if isinstance(payload, dict) else str(payload)
        return TurnResult(reply=question or "", awaiting_input=True)

    reply = ""
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            reply = str(message.content)
            break
    return TurnResult(
        reply=reply,
        new_artifacts=list(result.get("new_artifacts", [])),
        spawn_topic=result.get("spawn_topic") or None,
    )


def invoke_turn(user_id: str, topic: str, message: str, *, graph=None) -> TurnResult:
    """驱动一轮:发一条 ``(user_id, topic)`` 消息,取回复 + 本轮产物引用。"""
    graph = graph or get_graph()
    slug = topic_slug(topic)
    config = _config_for(user_id, slug)

    if _has_pending_interrupt(graph, config):
        # 这条消息是对中断提问的回答 → resume,跳过 Router 重新分类。
        result = graph.invoke(Command(resume=message), config)
    else:
        result = graph.invoke(
            {
                "messages": [HumanMessage(message)],
                "user_id": user_id,
                "topic": topic,
                "topic_slug": slug,
            },
            config,
        )
    return _interpret(result)
