"""ZPD/规划节点:选出「挑战刚刚好」的下一课范围(承接 teach §ZPD)。

SKILL.md §Zone Of Proximal Development 给智能体一条纪律:每节课都让学习者「挑战
刚刚好」;学习者没指定确切内容时,据 ``learning-records`` + ``MISSION.md`` 算出
最近发展区,选出最该教的那一个点。本节点忠实落地为一次「读记录+使命 → 产出
**单一、紧凑、紧扣 mission** 的下一课范围」的规划:

    read learning-records + MISSION.md   # 确定性读入(workspace,单一事实源)
    LLM 规划 -> 结构化「下一课范围」      # zpd 档模型(重认知),只产结构化输出
    写入图状态 next_lesson_scope          # 供同轮 Lesson 子图(#007)消费

**开局 vs 继续(#016 / §D1/§D2)**:`/teach` 的选题丰富度来自把 ZPD 推理**对话式呈现**
给学习者、可被反应(SKILL.md:84-89)。移植版曾把开局压成「静默单选 + 立即生成」,
丢失了这个选题时刻。现按纯文件事实判定:

- **开局**(``next_lesson_number == 1``,尚无编号课):产出 2-4 个候选首课 + 推荐,
  用 ``interrupt()`` 以学习者语言呈现,学习者选定后再顺 ``zpd→lesson`` 边生成「恰好
  一课」。若学习者已点名一个紧凑具体首课,honour 之、跳过菜单直出单课(§ZPD「may
  specify an exact thing」)。
- **继续**(已有编号课):仍单选、直出下一课,保持 ADR-0010 单轮体验。

承接要点:
- **单一、紧凑**(L3):scope 只圈一个 tightly-scoped 的点,不是大纲。
- **挑战刚刚好、不超工作记忆**(L4):落在最近发展区,据已学记录往上选一步。
- **不漂出 mission**(L2):选课以 mission 为锚,§ZPD 指令显式约束不漂到 mission 外。

质量由架构保证(承接「不寄望模型一次写好」):模型只产**结构化** scope,读
learning-records、把 scope 落进图状态都由本模块的确定性代码接管。本节点**不**写
任何工作区产物——「下一课范围」是 ZPD→Lesson 的轮内交接量,真正的课程 HTML 由
Lesson 子图(#007)产出(ADR-0003:不双写,文件只承载真正的 B/C 层产物)。
"""

from __future__ import annotations

import re

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from . import language, models, prompts, workspace
from .state import TeachState
from .workspace import workspace_dir
from pydantic import BaseModel, Field


# --- 结构化输出 schema(模型只产这个;落进图状态由确定性代码接管)----------------
class NextLessonScope(BaseModel):
    """ZPD 节点选出的「下一课范围」(单一、紧凑、紧扣 mission,落在最近发展区)。

    供下游 Lesson 创作子图(#007)消费:``title`` 决定课程文件名/标题,``objective``
    是这节课的「单一可达成的胜利」(L5),``rationale`` / ``mission_link`` 让创作与
    评估能审计「这节课为何此时、如何扣回 mission」。
    """

    title: str = Field(
        description="Short dash-case-friendly name for the lesson (the thing being taught)."
    )
    objective: str = Field(
        description="One sentence: the single tangible win the learner gets from this lesson."
    )
    rationale: str = Field(
        description="1-2 sentences grounding this choice in the learning records and mission."
    )
    mission_link: str = Field(
        description="One sentence tying the lesson back to the mission."
    )


class FirstLessonMenu(BaseModel):
    """开局(尚无编号课)时 ZPD 产出的首课候选清单(#016 / §D1)。

    ``candidates`` 复用 ``NextLessonScope``:一般给 2-4 个供学习者选;若学习者已点名一个
    具体首课,则只给 1 个(honour 之,下游跳过菜单直出)。``recommended`` 是候选里的推荐
    项索引(0-based)。菜单在 ``interrupt()`` 之前生成,故 ZPD 节点用 temperature=0 调用,
    保证 resume 重跑产出同一批候选、选定索引不错位(承接 mission 节点的重跑纪律)。
    """

    candidates: list[NextLessonScope] = Field(
        description=(
            "2-4 candidate first lessons ranked best-first, OR exactly 1 when the learner "
            "named a specific compact first lesson to honour."
        )
    )
    recommended: int = Field(
        description="0-based index into candidates of the recommended first lesson."
    )


# --- 公开节点入口 -------------------------------------------------------------
def zpd_node(state: TeachState) -> dict:
    """ZPD 能力节点:读 learning-records + mission → 选出下一课范围,写入图状态。

    开局(尚无编号课)走首课菜单(§D1);否则单选续课。开局/继续判定是确定性、纯文件
    事实(``next_lesson_number``,承接 ADR-0003),不引入新状态位。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    mission = workspace.read_text(directory, "MISSION.md") or ""
    records = workspace.read_learning_records(directory)
    # 已授课 manifest(#015 / §D5):committed 课程的内容级台账,据它禁止 ZPD 重选已覆盖
    # scope(learning-records 只在展示出理解时才写,不足以防重复)。
    manifest = workspace.read_lesson_manifest(directory)
    # Spacing 间隔复习信号(#024 / ADR-0012):据 Coverage Ledger 的授课时间戳 + 当前时间
    # 确定性派生「该复习什么」(教过超过间隔阈值的课列为到期,最久未复习的在前),喂进选课
    # 使 spacing 从隐性判断变为显式机制。旧 manifest 无时间戳时优雅退化为空信号(不报错)。
    spacing_review = workspace.derive_spacing_review(manifest)
    # Learner Notes(#022 / ADR-0012 三层记忆之第三层):偏好 / 节奏 / 反复卡点 / 未解决疑问 /
    # 系统背景,喂进选课使 ZPD 据学习者真实状态前瞻(如优先安排反复卡住的点)。
    learner_notes = workspace.read_learner_notes(directory) or ""
    last_human = _last_human_text(state.get("messages", []))
    # Workspace Language(#021 / ADR-0013):点名给选课 prompt 令 scope 文本随语言产出;
    # 首课菜单的确定性 chrome 也据它从常量表取,不再硬编中文。缺失回退默认语言。
    lang = state.get("workspace_language") or language.DEFAULT_LANGUAGE

    if workspace.next_lesson_number(directory) == 1:
        scope = _select_first_lesson(
            mission, records, manifest, last_human, lang, learner_notes, spacing_review
        )
    else:
        scope = _select_next_lesson(
            mission, records, manifest, last_human, lang, learner_notes, spacing_review
        )
    # 落进图状态供同轮 Lesson 子图消费;本节点不写工作区产物(理由见模块 docstring)。
    return {"next_lesson_scope": scope}


# --- 继续:单选下一课(已有编号课;保持 ADR-0010 单轮体验)---------------------
def _select_next_lesson(
    mission: str,
    records: list[str],
    manifest: list[dict],
    last_human: str,
    lang: str,
    learner_notes: str = "",
    spacing_review: list[dict] | None = None,
) -> dict:
    """据 mission + learning-records + manifest + Learner Notes + spacing 信号单选下一课(无 interrupt)。"""
    scope: NextLessonScope = models.get_model("zpd").with_structured_output(
        NextLessonScope
    ).invoke(
        [
            SystemMessage(
                prompts.zpd_system(
                    mission, records, last_human, manifest, lang, learner_notes, spacing_review
                )
            ),
            HumanMessage(last_human or "What should we learn next?"),
        ]
    )
    return scope.model_dump()


# --- 开局:首课菜单(候选 + 推荐 → interrupt 呈现 → 选定;或 honour 点名直出)----
def _select_first_lesson(
    mission: str,
    records: list[str],
    manifest: list[dict],
    last_human: str,
    lang: str,
    learner_notes: str = "",
    spacing_review: list[dict] | None = None,
) -> dict:
    """开局产出候选首课,interrupt 呈现供学习者选定;学习者点名具体首课则直出(§D1)。"""
    # 菜单在 interrupt 之前生成 → 必须确定性(temp 0):resume 时节点从头重跑,菜单须
    # 跨重跑产出同一批候选,否则选定索引会错位(承接 mission 节点的重跑纪律)。
    menu: FirstLessonMenu = models.get_model("zpd", temperature=0.0).with_structured_output(
        FirstLessonMenu
    ).invoke(
        [
            SystemMessage(
                prompts.zpd_first_lesson_system(
                    mission, records, manifest, last_human, lang, learner_notes, spacing_review
                )
            ),
            HumanMessage(last_human or "What should we learn first?"),
        ]
    )
    candidates = menu.candidates or []
    if not candidates:
        # 兜底:模型没给候选 → 退回单选,避免空菜单卡死(状态仍不丢)。
        return _select_next_lesson(
            mission, records, manifest, last_human, lang, learner_notes, spacing_review
        )

    recommended = menu.recommended if 0 <= menu.recommended < len(candidates) else 0

    # honour-that(§D1 / §ZPD「may specify an exact thing」):学习者已点名具体首课 →
    # 模型只给 1 个候选 → 跳过菜单直出,不硬塞选择。
    if len(candidates) == 1:
        return candidates[0].model_dump()

    # 否则:开局选题时刻 —— interrupt 把候选以 Workspace Language 呈现,选定后再顺 zpd→lesson 边生成。
    answer = interrupt(
        {"kind": "first_lesson_menu", "question": _render_menu(candidates, recommended, lang)}
    )
    index = _parse_choice(str(answer), len(candidates), recommended)
    return candidates[index].model_dump()


def _render_menu(candidates: list[NextLessonScope], recommended: int, lang: str) -> str:
    """把候选首课渲染成学习者可见菜单(结构性 chrome 随 Workspace Language 从常量表取,#021;
    候选标题/目标/理由是模型按语言产出的内容)。含推荐标记 + 每项理由。"""
    chrome = language.chrome(lang)
    lines = [chrome["menu_intro"], ""]
    for index, candidate in enumerate(candidates):
        mark = chrome["menu_recommended"] if index == recommended else ""
        lines.append(f"{index + 1}. {candidate.title}{mark}")
        if candidate.objective:
            lines.append(f"   {chrome['menu_objective_label']}{candidate.objective}")
        if candidate.rationale:
            lines.append(f"   {chrome['menu_why_label']}{candidate.rationale}")
        if candidate.mission_link:
            lines.append(f"   {chrome['menu_mission_label']}{candidate.mission_link}")
        lines.append("")
    lines.append(chrome["menu_choose_hint"].format(count=len(candidates)))
    return "\n".join(lines).rstrip()


def _parse_choice(answer: str, count: int, recommended: int) -> int:
    """从学习者回答里确定性解析出选中的候选索引(0-based);无法解析则回退到推荐项。

    interrupt 之后只跑一次(非重跑敏感),故用简单稳健的取首个整数序号;越界 / 无数字 →
    回退 recommended,保证永远返回一个合法索引。
    """
    match = re.search(r"\d+", answer)
    if match:
        chosen = int(match.group()) - 1
        if 0 <= chosen < count:
            return chosen
    return recommended


# --- 小工具 -------------------------------------------------------------------
def _last_human_text(messages: list[AnyMessage]) -> str:
    """取最近一条人类消息文本。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


__all__ = ["zpd_node", "NextLessonScope", "FirstLessonMenu"]
