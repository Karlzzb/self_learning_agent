"""Wisdom 节点:先尝试回答,再把学习者引导到高声望社区(承接 teach §Acquiring Wisdom + P4)。

SKILL.md §Acquiring Wisdom 定下默认姿态:当学习者提出需要**实战智慧**的问题时,智能体先
尝试回答,但**最终委托给一个社区**——一个学习者能在真实世界检验技能的地方(论坛、subreddit、
线下课、本地兴趣小组)。智能体应尝试寻找高声望社区让学习者加入;若学习者表达不想加入社区的
偏好,尊重它(opt-out)。Router 判 ``wisdom`` 时路由到这里,本节点:

    读 MISSION.md + RESOURCES.md(尝试回答的事实依据;已 curate 的社区可在回复中引用)
    search(query) -> 社区候选          # 唯一触网点,藏在可换接口后(search.py);够不着可容忍
    LLM 甄别(强档):据已 curate 知识尝试回答 + 从候选里甄别高声望社区 + 识别 opt-out
    确定性代码 -> upsert RESOURCES.md 的 Wisdom 段(只采纳 trusted 候选;opt-out 持久记录)

**控制流**:遵循 ADR-0001「每条学习者消息调用一次图」。本节点对最新一条 wisdom 问题给出
单轮响应(尝试回答 + 社区引导),学习者的下一句作为**新一轮**再次经 Router 路由。不引入
interrupt:wisdom 是开放型对话,逐轮响应更贴合(与 Assessment 同构)。

**失败姿态(P1 / ADR-0009,「Never trust your parametric knowledge」)**:社区 URL 与事实性
论断**绝不脑补**。社区只取自 ``search`` 返回的候选(模型对每条给 ``trusted`` 判定,代码**只
采纳 trusted 的**);搜索够不着(空候选 / 硬故障)不阻断「尝试回答」这一默认姿态——本节点
仍正常回答,只是这一轮不新增社区。质量由架构保证(高信任筛选是确定性的),不寄望模型自律。

**怎么写 vs 写什么**:**写哪些社区 / 是否 opt-out**是本节点的教学判断;**怎么写**(RESOURCES.md
的 Wisdom 段格式 / 去重 / opt-out sticky)收敛在 ``workspace.upsert_communities`` 的纯文件原语。
本节点**不**碰 Knowledge / Gaps 段(那是 Research 节点 #004 的职责),只增量维护 Wisdom 段。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from pydantic import BaseModel, Field

from . import language, models, prompts, search, workspace
from .state import TeachState
from .workspace import workspace_dir

# 模型违反 schema / 罕见降级时的兜底回复由 Workspace Language 从 chrome 常量表取(#021):
# 随语言的正文由模型在 reply 给出;此兜底保证「先尝试回答」永不为空且语言一致,不硬编中文。


# --- 结构化输出 schema(模型只产这个;社区落盘 / 高信任筛选由确定性代码接管)--------
class WisdomCommunity(BaseModel):
    """一条社区资源的甄别结果。``trusted`` 由代码用于高信任筛选(只采纳 trusted 的)。"""

    name: str = Field(description="Community name, e.g. 'r/MachineLearning' or 'Local: ...'.")
    url: str | None = Field(
        default=None,
        description="URL from the provided candidates if online; null for offline groups. Never invent one.",
    )
    annotation: str = Field(description="One line: what it covers and when to reach for it.")
    trusted: bool = Field(
        description="True only for well-moderated, high-reputation communities."
    )


class WisdomResponse(BaseModel):
    """Wisdom 节点的结构化产物(承接 §Acquiring Wisdom)。

    ``reply`` 是「先尝试回答 + 社区引导」的学习者可见回复(随学习者语言)。``communities``
    是从给定候选里甄别出的社区(代码只采纳 ``trusted`` 的);``community_opt_out`` 由模型据
    学习者偏好判定,代码据其持久记录「不再推社区」(respect opt-out)。
    """

    reply: str = Field(
        description="Learner-facing answer woven with a community pointer, in the learner's language."
    )
    communities: list[WisdomCommunity] = Field(default_factory=list)
    community_opt_out: bool = Field(
        default=False,
        description="True if the learner has said they don't want to join communities (P4 respect opt-out).",
    )


# --- 公开节点入口 -------------------------------------------------------------
def wisdom_node(state: TeachState) -> dict:
    """Wisdom 能力节点:先尝试回答 → 甄别高声望社区委托过去 → 记录 opt-out 偏好。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    topic = state.get("topic", "")
    mission = workspace.read_text(directory, "MISSION.md") or ""
    resources_md = workspace.read_text(directory, "RESOURCES.md") or ""
    transcript: list[AnyMessage] = list(state.get("messages", []))
    # Workspace Language(#021 / ADR-0013):尝试回答 reply 随持久化语言;兜底也据它取。
    lang = state.get("workspace_language") or language.DEFAULT_LANGUAGE

    # 1) 找社区(唯一触网点)。够不着 / 硬故障 → 空候选;**不**阻断「尝试回答」的默认姿态
    #    (P4:回答不依赖找到社区)。社区 URL 只取自候选,绝不脑补(P1)。
    try:
        candidates = search.search(_community_query(topic, mission))
    except Exception:  # noqa: BLE001 — 搜索硬故障收敛为「这一轮没有社区候选」,仍照常回答
        candidates = []

    # 2) 甄别(wisdom 档模型):据已 curate 知识尝试回答 + 从候选甄别社区 + 识别 opt-out。
    response: WisdomResponse = models.get_model("wisdom").with_structured_output(
        WisdomResponse
    ).invoke(
        [
            SystemMessage(
                prompts.wisdom_system(
                    topic, mission, resources_md, _format_candidates(candidates), lang
                )
            ),
            *transcript,
        ]
    )

    # 3) 高信任筛选(确定性:架构保证质量)。学习者 opt-out 时不新增社区(respect it),
    #    但仍记录偏好;否则把 trusted 社区增量 upsert 进 RESOURCES.md 的 Wisdom 段。
    trusted = [c for c in response.communities if c.trusted]
    to_add = [] if response.community_opt_out else trusted
    if to_add or response.community_opt_out:
        workspace.upsert_communities(
            directory,
            [workspace.Community(c.name, c.url, c.annotation) for c in to_add],
            opt_out=response.community_opt_out,
            topic=topic,
        )
    fallback = language.chrome(lang)["wisdom_fallback_reply"]
    return {"messages": [AIMessage(response.reply or fallback)]}


# --- 小工具 -------------------------------------------------------------------
def _community_query(topic: str, mission: str) -> str:
    """据主题 + 使命拼出「找高声望社区」的检索 query(锚定在使命上)。"""
    parts = [
        part
        for part in (topic, mission.strip(), "high-reputation community forum")
        if part
    ]
    return "\n".join(parts) if parts else topic


def _format_candidates(candidates: list[search.Candidate]) -> str:
    """把社区候选列表渲染成喂给甄别模型的文本(逐条:标题 / 链接 / 摘要)。"""
    if not candidates:
        return ""
    blocks = []
    for index, candidate in enumerate(candidates, start=1):
        block = f"{index}. {candidate.title}\n   URL: {candidate.url}"
        if candidate.snippet:
            block += f"\n   {candidate.snippet}"
        blocks.append(block)
    return "Community candidates:\n\n" + "\n".join(blocks)


__all__ = ["wisdom_node", "WisdomResponse", "WisdomCommunity"]
