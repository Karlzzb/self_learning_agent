"""Assessment 节点:对话式评估学习者表现 + 据证据写学习记录(承接 teach §Skills + P6)。

ADR-0002 把课内反馈拆成两半:(i) 课程 HTML 内置 JS 处理闭合型练习的即时判分(已在
Lesson 子图落地);(ii) **对话式评估**由智能体处理开放型 / wisdom 级检验并更新学习
记录——这就是本节点。学习者做完课回来,说出他们的理解 / 作答 / 疑问时,Router 判
``assess`` 路由到这里,本节点:

    读 MISSION.md + learning-records(确定性读入,单一事实源)
    LLM 评估这轮对话(强档):据表现给反馈、追问误解,并据 P6 决定是否写学习记录
    达证据门 → 确定性追加一条学习记录(供下一轮 ZPD 读取,影响下一课)
    回一条学习者可见的反馈(随学习者语言)

**控制流**:遵循 ADR-0001「每条学习者消息调用一次图」。评估是**单轮**响应——本节点
对最新一条消息评估、回复(可含一道追问),学习者的下一句作为**新一轮**再次经 Router
路由回 ``assess``。不引入 interrupt:开放型对话没有 Mission 访谈那样明确的「问到够了
就落盘」终点,逐轮响应更贴合(也避免 resume 重跑的复杂度)。

**P6 学习记录纪律(证据级,非流水账)**:写记录是高门槛动作。模型按 LEARNING-RECORD-
FORMAT「When to write」判定四类证据之一(展示真正理解 / 披露先验知识 / 纠正误解 /
Mission 迁移);仅被「覆盖过」的材料不算学习,不写。**这道纪律不只寄望模型自律**:本
节点加一道确定性闸门——``evidence_kind == "none"`` 或缺标题/正文时绝不落盘(承接「质量
由架构保证」)。**写不写**是教学判断(在此),**怎么写**(编号/命名/格式)是确定性
原语(``workspace.append_learning_record``)。

**不改 MISSION.md**:即便评估发现 Mission 迁移(证据类型 4),本节点也只写一条学习
记录,**不**径自改写 MISSION.md——更新使命需先与学习者确认(P3),那是 Mission(change)
节点的职责。本节点只负责评估与记录。
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from pydantic import BaseModel, Field

from . import language, models, prompts, workspace
from .state import CapturedNote, TeachState
from .workspace import workspace_dir

# 模型违反 schema / 罕见降级时的兜底回复由 Workspace Language 从 chrome 常量表取(#021):
# 随语言的正文由模型在 reply 给出;此兜底保证回复永不为空且语言一致,不再硬编中文。


# --- 结构化输出 schema(模型只产这个;编号/落盘/证据闸门由确定性代码接管)----------
class Assessment(BaseModel):
    """一次对话式评估的结构化产物。

    ``write_record`` / ``evidence_kind`` 把 P6「写不写」学习记录的判断交给模型,但落盘
    与否由本模块的确定性闸门复核(``evidence_kind == "none"`` 时绝不写)。``glossary_*``
    把 P7「促不促词条入表」的判断交给模型——与 P6 同构(证据级、由本节点把关):仅当这次
    交流证明学习者**理解**了某术语才填,落盘与否同样由确定性闸门复核(术语/定义齐备方写)。
    ``record_*`` / ``glossary_*`` 仅在达各自证据门时使用;``reply`` 是学习者可见的反馈
    (随学习者语言,可含一道追问)。
    """

    write_record: bool = Field(
        description="True ONLY when one of the four learning-record evidence criteria holds."
    )
    evidence_kind: Literal[
        "understanding", "prior_knowledge", "misconception_corrected", "mission_shift", "none"
    ] = Field(
        description="Which evidence criterion was met; 'none' when nothing qualifies."
    )
    record_title: str | None = Field(
        default=None, description="Short learning-record title, when write_record is true."
    )
    record_body: str | None = Field(
        default=None,
        description="1-3 sentences: what was learned/established and why it matters, when write_record is true.",
    )
    # LEARNING-RECORD-FORMAT「Optional sections」(#023 / ADR-0012):前瞻信号,仅在有价值时填。
    # 触发纪律不变——这些只是给一条**已达证据门**的记录加厚,不降低写不写记录的门槛。
    record_evidence: str | None = Field(
        default=None,
        description=(
            "Optional: how the learner demonstrated this understanding (a question answered, "
            "an exercise completed, prior experience cited). Fill only when it adds genuine "
            "value and write_record is true; else null."
        ),
    )
    record_implications: str | None = Field(
        default=None,
        description=(
            "Optional: what this unlocks or rules out for future sessions. Fill only when "
            "non-obvious and write_record is true; else null."
        ),
    )
    # Supersession(#023 / LEARNING-RECORD-FORMAT「Supersession」):后写记录纠正/深化了旧
    # 记录时,给出被取代旧记录的编号(NNNN)。旧记录不删除,只被标 superseded(保留理解演化史,
    # 使过时假设不再误导选课)。仅在 write_record 为真且确有旧记录被取代时给出;否则 null。
    supersedes_record: int | None = Field(
        default=None,
        description=(
            "Optional: the number (NNNN) of an existing learning record this new record "
            "supersedes because the learner's understanding corrected or deepened it. The "
            "old record is kept but marked superseded, never deleted. Null when nothing is "
            "superseded."
        ),
    )
    # P7 词汇表促入(承接 GLOSSARY-FORMAT.md Rules + _GLOSSARY_PROMOTION_INSTRUCTION):
    # 仅当学习者真正理解某术语时填 ``glossary_term`` + ``glossary_definition``;否则留空。
    # 与学习记录是**独立**决定(一轮可能促词条而不写记录,反之亦然——「不要把已入表的
    # 术语再重复写成学习记录」)。
    glossary_term: str | None = Field(
        default=None,
        description="The single canonical term to add/revise to the glossary, or null if none qualifies.",
    )
    glossary_definition: str | None = Field(
        default=None,
        description="Tight, opinionated definition (1-2 sentences saying what the term IS), or null.",
    )
    glossary_aliases: list[str] = Field(
        default_factory=list,
        description="Other words for the same concept to avoid in favour of the canonical term (may be empty).",
    )
    reply: str = Field(
        description="Learner-facing feedback in the learner's language; may probe a misconception."
    )
    # Learner Notes 捕捉(#022 / ADR-0012):评估对话里暴露的反复卡点 / 未解决疑问 / 偏好 /
    # 背景。与 write_record / glossary 促入**独立**——未解决疑问落此(open_question),而**不**
    # 作为 learning-record 的第五类证据。
    learner_notes: list[CapturedNote] = Field(
        default_factory=list,
        description=(
            "Learner notes captured this turn (preferences / pace / sticking points / open "
            "questions / background). May be empty. Independent of write_record."
        ),
    )


# --- 公开节点入口 -------------------------------------------------------------
def assessment_node(state: TeachState) -> dict:
    """Assessment 能力节点:评估这轮对话 → 据证据写学习记录 / 促词条入表 → 回反馈。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    mission = workspace.read_text(directory, "MISSION.md") or ""
    records = workspace.read_learning_records(directory)
    glossary_md = workspace.read_text(directory, "GLOSSARY.md") or ""
    # Learner Notes(#022 / ADR-0012):既有笔记带进评估 prompt(供模型看已记过什么、避免重复)。
    learner_notes = workspace.read_learner_notes(directory) or ""
    transcript: list[AnyMessage] = list(state.get("messages", []))
    # Workspace Language(#021 / ADR-0013):反馈 reply、写入的 learning-record 标题/正文、
    # 促入的 glossary 词条都随持久化语言产出;兜底回复也据它取。缺失回退默认语言。
    lang = state.get("workspace_language") or language.DEFAULT_LANGUAGE

    assessment: Assessment = models.get_model("assessment").with_structured_output(
        Assessment
    ).invoke(
        [
            SystemMessage(
                prompts.assessment_system(mission, records, glossary_md, lang, learner_notes)
            ),
            *transcript,
        ]
    )

    # P6 确定性闸门:只有真出现四类证据之一、且记录标题/正文齐备,才落盘学习记录。
    # 纯「覆盖过」(evidence_kind == "none")绝不写——纪律由架构保证,不只寄望模型自律。
    if _should_record(assessment):
        # 新记录将拿到的编号(供 supersession 写「superseded by LR-NNNN」),在 append 前取。
        new_number = workspace.next_record_number(directory)
        workspace.append_learning_record(
            directory,
            assessment.record_title,
            assessment.record_body,
            evidence=assessment.record_evidence,
            implications=assessment.record_implications,
        )
        # Supersession(#023):仅当新记录确实取代一条**已存在**的旧记录才标注(闸门在此,
        # 不只寄望模型)。旧记录保留不删除,只被标 superseded——理解演化史本身是信号,且使
        # 过时假设不再误导下一轮 ZPD 选课(承接 LEARNING-RECORD-FORMAT「Supersession」)。
        if _should_supersede(assessment, directory, new_number):
            workspace.supersede_learning_record(
                directory, assessment.supersedes_record, new_number
            )
    # P7 确定性闸门(同 P6:模型判「促不促」,代码把关「怎么写」+ 落盘):仅当术语与定义
    # 齐备才 upsert——半填的促入被架构拦下,不只寄望模型自律。``upsert`` 就地修订同名词条。
    if _should_promote_glossary(assessment):
        workspace.upsert_glossary_term(
            directory,
            assessment.glossary_term,
            assessment.glossary_definition,
            assessment.glossary_aliases,
            topic=state.get("topic", ""),
        )
    # Learner Notes 捕捉缝(#022 / ADR-0012):怎么写(合并/去重/落盘)由确定性原语接管;
    # 未解决疑问落 NOTES(open_question),不写 learning-records(不新增第五类证据)。
    if assessment.learner_notes:
        workspace.append_learner_notes(
            directory,
            [workspace.LearnerNote(note.category, note.text) for note in assessment.learner_notes],
        )
    fallback = language.chrome(lang)["assessment_fallback_reply"]
    return {"messages": [AIMessage(assessment.reply or fallback)]}


# --- 小工具 -------------------------------------------------------------------
def _should_record(assessment: Assessment) -> bool:
    """P6 确定性闸门:四类证据之一成立(非 none)且记录正文齐备时才写。"""
    return bool(
        assessment.write_record
        and assessment.evidence_kind != "none"
        and assessment.record_title
        and assessment.record_body
    )


def _should_supersede(assessment: Assessment, directory, new_number: int) -> bool:
    """确定性闸门:模型给了一个**存在的、非自身**旧记录编号时才标 superseded。

    防两类脏动作:指向不存在的编号(模型幻觉),或指向刚写的新记录自身(自我取代)。
    ``supersedes_record`` 缺省 ``None`` 时(绝大多数轮次)直接不触发。
    """
    target = assessment.supersedes_record
    return bool(
        target is not None
        and target != new_number
        and workspace.learning_record_exists(directory, target)
    )


def _should_promote_glossary(assessment: Assessment) -> bool:
    """P7 确定性闸门:术语与定义齐备时才促入词汇表(独立于学习记录决定)。

    模型已被指示「仅当学习者真正理解某术语才填」(introduction is not understanding);
    本闸门只把关「字段齐备」——半填(有术语无定义,反之亦然)绝不落盘,避免脏词条。
    """
    return bool(
        assessment.glossary_term
        and assessment.glossary_term.strip()
        and assessment.glossary_definition
        and assessment.glossary_definition.strip()
    )


__all__ = ["assessment_node", "Assessment"]
