"""Research 节点:从高信任资源采集知识,甄别后写入 ``RESOURCES.md``。

承接 teach §Knowledge + RESOURCES-FORMAT(见 ``prompts.research_system``):在
``RESOURCES.md`` 充实之前,智能体的首要任务是找到高质量资源让学习者获取知识
(SKILL.md §Philosophy)。本节点把这条落地为一个三段式确定性流水:

    search(query) -> 候选          # 唯一触网点,藏在可换接口后(search.py)
    LLM 甄别 -> 结构化草稿          # research 档模型,只产结构化输出
    确定性代码 -> 渲染 RESOURCES.md  # 高信任筛选、分组、标注、落盘都由代码接管

**失败姿态(P1 / ADR-0009,「Never trust your parametric knowledge」)**:
- 搜索够不着(返回空)或服务硬故障(抛异常)→ 坦白告知、**暂缓该课**,绝不降级
  用脑补知识;不写任何未经核实的 ``RESOURCES.md``。
- 候选都不够可信(模型判定 ``defer`` 或筛完两组皆空)→ 同样暂缓。
- 暂缓时本节点正常返回(只带一条 AIMessage),图照常走到 finalize,checkpointer
  完成存档——学习者下次回来可无损续接(此时仍无 RESOURCES.md → 再次进入本节点)。

质量由架构保证(承接「不寄望模型一次写好」):高信任筛选是确定性的——模型对每条
候选给出 ``trusted`` 判定,代码**只采纳 trusted 的**;RESOURCES.md 的分组/标注/
Gaps/社区偏好都由确定性渲染函数按 RESOURCES-FORMAT 产出。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import config, language, models, prompts, search, workspace
from .state import TeachState
from .workspace import workspace_dir

# 暂缓 / 完成时给学习者的兜底回复由 Workspace Language 从 chrome 常量表取(#021 / ADR-0013):
# 模型给了 reply 时优先用模型的、随语言的版本;此表是模型违反 schema / 未给 reply 时的
# 语言一致兜底,保证「坦白告知」永远不为空、不再硬编中文。


# --- 结构化输出 schema(模型只产这个;文件写入由确定性代码接管)----------------
class ResourceEntry(BaseModel):
    """一条知识资源的甄别结果。``trusted`` 由代码用于高信任筛选。"""

    title: str = Field(description="Title prefixed with type, e.g. 'Book: ...', 'Article: ...'.")
    url: str = Field(description="Canonical URL from the provided candidates. Never invent one.")
    annotation: str = Field(description="One line: what it covers and when to reach for it.")
    trusted: bool = Field(description="True only for genuinely high-trust sources.")


class CommunityEntry(BaseModel):
    """一条 Wisdom(社区)资源。``url`` 可空(线下社区)。"""

    name: str = Field(description="Community name, e.g. 'r/MachineLearning' or 'Local: ...'.")
    url: str | None = Field(default=None, description="URL if online; null for offline groups.")
    annotation: str = Field(description="One line: what it covers and when to reach for it.")
    trusted: bool = Field(description="True only for well-moderated, high-reputation communities.")


class ResourcesDraft(BaseModel):
    """Research 节点的结构化草稿(承接 §Knowledge + RESOURCES-FORMAT)。"""

    knowledge: list[ResourceEntry] = Field(default_factory=list)
    wisdom: list[CommunityEntry] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="Areas the mission needs but no candidate covers (drives future search).",
    )
    community_opt_out: bool = Field(
        default=False,
        description="True if the learner has said they don't want to join communities (P2).",
    )
    defer: bool = Field(
        default=False,
        description="True if NO candidate is trustworthy enough to teach from.",
    )
    reply: str = Field(
        default="",
        description="Learner-facing message, in the learner's language.",
    )


# --- 公开节点入口 -------------------------------------------------------------
def research_node(state: TeachState) -> dict:
    """Research 能力节点:采集 → 甄别(含对既有资源重新甄别 / 剪枝)→ 写 RESOURCES.md;够不着则暂缓。

    **可重跑 / 合并语义(#025):**本节点幂等——重跑时把**既有已 curate 的知识源**折进
    这一趟甄别池,与新候选一并交给模型重判,让它剪掉已失效 / 不可信 / 离题的旧源(承接
    RESOURCES-FORMAT「Prune ruthlessly」)。剪枝经既有单一渲染器整份落盘;**既有社区段
    只增不减**(union),使 Wisdom 节点(#010)写入的社区不被 research 剪枝破坏。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    topic = state.get("topic", "")
    mission = workspace.read_text(directory, "MISSION.md") or ""
    last_human = _last_human_text(state.get("messages", []))
    subtopics = _mission_subtopics(mission)
    queries = _build_queries(topic, mission, last_human, subtopics)
    # Workspace Language(#021 / ADR-0013):RESOURCES 注解与 reply 随持久化语言产出(源标题
    # + URL 原样保留);兜底回复也据它从 chrome 取。缺失回退默认语言。
    lang = state.get("workspace_language") or language.DEFAULT_LANGUAGE
    chrome = language.chrome(lang)

    # 既有 RESOURCES.md(#025 合并语义):重跑时读回已 curate 的资源。全新学习者返回 None,
    # 本节点退化为原 greenfield 行为(不劣于改前)。既有社区 + opt-out 偏好据它保留 / sticky。
    existing = workspace.read_resources(directory, topic)

    # 1) 多查询采集(#018 / §D7):对关键子主题各发一条查询,汇总去重成更厚的候选池,
    #    让下游 draft 有足量可引用源。唯一触网点仍藏在 search() 接口后(ADR-0007)。
    #    逐条查询容错:某条硬故障就跳过,只要有一条查到候选就继续;全部够不着 → 失败姿态
    #    暂缓,绝不降级用脑补知识(P1 / ADR-0009)。暂缓**不改写**既有 RESOURCES.md(不 wipe)。
    candidates = _gather_candidates(queries)
    if not candidates:
        return _defer(chrome["research_defer_unreachable_reply"])

    # 2) 甄别(research 档模型,只产结构化草稿)。把关键子主题一并交给模型,要求跨子主题
    #    覆盖、显式标注 Gaps;覆盖不足以支撑教学时由模型 defer(深度门,#018 / §D7)。
    #    #025:既有已 curate 的知识源作为「待重新甄别的旧源」一并喂入,让模型对旧 + 新统一
    #    重判——仍可信/在题的保留,已失效/浅薄/离题的剪掉(prune),不再盲目累积坏资源。
    draft: ResourcesDraft = models.get_model("research").with_structured_output(
        ResourcesDraft
    ).invoke(
        [
            SystemMessage(prompts.research_system(topic, mission, subtopics, lang)),
            HumanMessage(_format_candidates(candidates, existing)),
        ]
    )

    # 3) 高信任筛选(确定性:架构保证质量,不寄望模型自律)。旧源被判 trusted=False 即被剪掉。
    knowledge = [entry for entry in draft.knowledge if entry.trusted]
    wisdom = [entry for entry in draft.wisdom if entry.trusted]
    if draft.defer or (not knowledge and not wisdom):
        # 一条可信的都没有 → 暂缓;**保留**既有 RESOURCES.md(不把已有好资源 wipe 成空)。
        return _defer(draft.reply or chrome["research_defer_no_trust_reply"])

    # 4) 确定性渲染 + 落盘:把甄别后的高信任源映射成 ``ResourcesDoc``,经 RESOURCES.md
    #    的唯一渲染器(workspace.write_resources)落盘——与 Wisdom 节点(#010)共用同一
    #    渲染器/解析器,避免两套渲染逻辑漂移(ADR-0003:文件是 B 层单一事实源)。
    #    #025:Knowledge 用重新甄别后的高信任集(旧坏源已剪);社区**只增不减**——既有社区
    #    保留、research 新甄别的可信社区并入(dedup),故 Wisdom 段不被 research 剪枝破坏;
    #    opt-out 一旦为真即 sticky(承接 upsert_communities 的既有约束)。
    communities = _merge_communities(existing, wisdom)
    opt_out = (existing.community_opt_out if existing else False) or draft.community_opt_out
    doc = workspace.ResourcesDoc(
        topic=topic,
        knowledge=[
            workspace.KnowledgeSource(e.title, e.url, e.annotation) for e in knowledge
        ],
        communities=communities,
        gaps=list(draft.gaps),
        community_opt_out=opt_out,
    )
    workspace.write_resources(directory, doc)
    return {"messages": [AIMessage(draft.reply or chrome["research_done_reply"])]}


def _merge_communities(
    existing: workspace.ResourcesDoc | None, wisdom: list[CommunityEntry]
) -> list[workspace.Community]:
    """合并语义(#025):既有社区**全部保留**,research 新甄别的可信社区并入(按 (name,url)
    大小写不敏感去重)。社区**只增不减**——research 的剪枝只作用于 Knowledge,绝不删除
    Wisdom 节点(#010)写入的社区,故两节点共用同一渲染器的既有约束不被破坏。
    """
    result: list[workspace.Community] = list(existing.communities) if existing else []
    seen = {(c.name.lower(), c.url) for c in result}
    for entry in wisdom:
        key = (entry.name.lower(), entry.url)
        if key not in seen:
            result.append(workspace.Community(entry.name, entry.url, entry.annotation))
            seen.add(key)
    return result


# --- 失败姿态 -----------------------------------------------------------------
def _defer(reply: str) -> dict:
    """暂缓该课:只回一条坦白消息,不写任何产物(checkpointer 仍会存档本轮)。"""
    return {"messages": [AIMessage(reply)]}


# --- 多查询采集(#018 / §D7)---------------------------------------------------
def _mission_subtopics(mission: str) -> list[str]:
    """从 MISSION.md 抽出「关键子主题」——即 bullet 行(尤其 ## Success looks like 下)。

    使命的成功标准 bullet 正是这门学习需要覆盖的具体子主题(承接 MISSION-FORMAT),
    用它作多查询的子主题来源:纯确定性、不加 LLM 规划(ADR-0007 极简工具面)。去重、
    保序。无 bullet 时返回空,``_build_queries`` 退化为单查询(不劣于改前行为)。
    """
    subtopics: list[str] = []
    for line in mission.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item and item not in subtopics:
                subtopics.append(item)
    return subtopics


def _build_queries(
    topic: str, mission: str, last_human: str, subtopics: list[str]
) -> list[str]:
    """据主题 + 使命 + 学习者最新一句 + 关键子主题,拼出一组检索 query(有界、去重、保序)。

    第一条是锚定使命的总览 query(承接改前 ``_build_query`` 行为);其余每条对准一个关键
    子主题,让候选池覆盖更全。上限 ``config.RESEARCH_MAX_QUERIES``,防查询数发散。
    """
    queries = [_build_query(topic, mission, last_human)]
    for subtopic in subtopics:
        query = f"{topic} {subtopic}".strip()
        if query and query not in queries:
            queries.append(query)
    return queries[: config.RESEARCH_MAX_QUERIES]


def _gather_candidates(queries: list[str]) -> list[search.Candidate]:
    """逐条查询采集并按 URL 去重汇总(保序)。逐条容错:硬故障的查询跳过。

    唯一触网点仍是 ``search()``(ADR-0007)。全部查询够不着 / 都硬故障 → 返回空,
    由调用方走失败姿态暂缓(不脑补,P1 / ADR-0009)。
    """
    seen: set[str] = set()
    gathered: list[search.Candidate] = []
    for query in queries:
        try:
            results = search.search(query)
        except Exception:  # noqa: BLE001 — 单条查询硬故障:跳过,继续其余查询
            continue
        for candidate in results:
            key = _normalize_url(candidate.url)
            if key and key not in seen:
                seen.add(key)
                gathered.append(candidate)
    return gathered


def _normalize_url(url: str) -> str:
    """URL 规范化(去重键):去首尾空白、去 fragment、去末尾斜杠。"""
    return (url or "").strip().split("#", 1)[0].rstrip("/")


# --- 小工具 -------------------------------------------------------------------
def _build_query(topic: str, mission: str, last_human: str) -> str:
    """据主题 + 使命 + 学习者最新一句拼出检索 query(锚定在使命上)。"""
    parts = [part for part in (topic, mission.strip(), last_human.strip()) if part]
    return "\n".join(parts) if parts else topic


def _format_candidates(
    candidates: list[search.Candidate],
    existing: workspace.ResourcesDoc | None = None,
) -> str:
    """把候选列表渲染成喂给甄别模型的文本(逐条:标题 / 链接 / 摘要)。

    #025 合并语义:若已有 curate 的 RESOURCES.md,把**既有知识源**作为「待重新甄别的
    现存资源」一并附上,让模型对旧 + 新统一重判——旧源若已失效 / 不可信 / 离题就剪掉
    (不再放进 ``knowledge``),仍在题就保留。既有社区不在此重判(社区只增不减,由
    ``_merge_communities`` 保留),故此处只附知识源。
    """
    blocks = []
    for index, candidate in enumerate(candidates, start=1):
        block = f"{index}. {candidate.title}\n   URL: {candidate.url}"
        if candidate.snippet:
            block += f"\n   {candidate.snippet}"
        blocks.append(block)
    text = "Search candidates:\n\n" + "\n".join(blocks)

    if existing and existing.knowledge:
        prior = []
        for index, source in enumerate(existing.knowledge, start=1):
            block = f"{index}. {source.title}\n   URL: {source.url}"
            if source.annotation:
                block += f"\n   {source.annotation}"
            prior.append(block)
        text += (
            "\n\nExisting curated knowledge sources (re-vet these against the current "
            "mission: keep the ones still trustworthy and on-mission, prune any that are "
            "now stale, wrong, shallow, or off-mission by leaving them out):\n\n"
            + "\n".join(prior)
        )
    return text


def _last_human_text(messages: list[AnyMessage]) -> str:
    """取最近一条人类消息文本。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


__all__ = [
    "research_node",
    "ResourceEntry",
    "CommunityEntry",
    "ResourcesDraft",
]
