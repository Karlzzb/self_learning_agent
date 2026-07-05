"""Mission 节点:把教学锚定在学习者的真实使命上(承接 teach §The Mission)。

SKILL.md §The Mission 给智能体两条纪律,本节点忠实落地为两种模式:

- **establish**(``MISSION.md`` 未填充):访谈学习者「为什么想学这个」,据此写出
  ``MISSION.md``(一个工作区一个 Mission)。SKILL.md 第 75 行:「your first job
  should be to question the user on why they want to learn this」。
- **change**(学习者想改变使命):**先与学习者确认**,确认后更新 ``MISSION.md``
  并追加一条 Learning Record。SKILL.md 第 79 行:「update the MISSION.md and add
  a learning record... Confirm with the user before changing the mission」(=P3)。

控制流承接 ADR-0001:用 ``interrupt()`` 暂停问学习者,resume 时节点**从头重跑**,
``interrupt()`` 直接返回上次的回答而不再暂停。重跑语义要求:被 interrupt 之前的
LLM 决策必须跨重跑稳定,否则多个 interrupt 的索引会错位——因此本节点所有「在
interrupt 之前」的模型调用都走 ``temperature=0``(见 ``models.get_model``)。

质量由架构保证(承接「不寄望模型一次写好」):模型只产**结构化输出**,文件写入、
学习记录编号、interrupt 控制流全部由本模块的确定性代码接管。
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from . import language, models, prompts, workspace
from .state import CapturedNote, TeachState
from .tenancy import topic_slug
from .workspace import workspace_dir

# 访谈最多追问几轮(把 interrupt 循环限定在有界范围,兜底强制落盘)。
# SKILL.md 要求「push back on vagueness」,但学习者工作记忆有限,不宜无限追问。
MAX_INTERVIEW_QUESTIONS = 4

# Mission 节点所有「interrupt 之前」的决策都用确定性温度(理由见模块 docstring)。
_DETERMINISTIC = 0.0

# 兜底文案由 Workspace Language 从 chrome 常量表取(#021 / ADR-0013),不再硬编中文:仅在模型
# 违反 schema / 罕见降级时触发;正常路径用模型按语言产出的 reply。establish 是语言检测点,
# 语言尚未持久化,故此处兜底据学习者文本确定性判语言(``detect_language``);change 模式已有
# 持久化语言,据状态取。
# 访谈轮次用尽时,用一条「请据现有对话现在就写出使命」的推动指令逼模型落盘。
_FORCE_WRITE_NUDGE = (
    "We have interviewed enough. Based on everything above, write the "
    "MISSION.md now (action = write)."
)


# --- 结构化输出 schema --------------------------------------------------------
class MissionStep(BaseModel):
    """访谈每一步的结构化决策:再问一个问题,还是落盘使命。"""

    action: Literal["ask", "write"] = Field(
        description="'ask' to ask one more question; 'write' to write MISSION.md now."
    )
    question: str | None = Field(
        default=None, description="The single next question, when action is 'ask'."
    )
    mission_markdown: str | None = Field(
        default=None, description="Full MISSION.md content, when action is 'write'."
    )
    reply: str | None = Field(
        default=None, description="A short learner-facing message, when action is 'write'."
    )
    language: str | None = Field(
        default=None,
        description=(
            "ISO 639-1 code (e.g. 'zh', 'en') of the language you are writing MISSION.md and "
            "reply in — i.e. the learner's language. Set it when action is 'write'."
        ),
    )
    # Learner Notes 捕捉(#022 / ADR-0012):访谈里学习者顺带暴露的偏好 / 节奏 / 反复卡点 /
    # 未解决疑问 / 系统背景,随 MISSION.md 一起落盘(何时写=此教学判断,怎么写=确定性原语)。
    learner_notes: list[CapturedNote] = Field(
        default_factory=list,
        description=(
            "Learner notes captured this turn (preferences / pace / sticking points / open "
            "questions / background). May be empty. Set alongside action='write'."
        ),
    )


class Confirmation(BaseModel):
    """学习者是否确认变更使命。"""

    confirmed: bool = Field(description="True only on a clear yes to changing the mission.")


class MissionChange(BaseModel):
    """变更使命的结构化产物:新使命 + 一条学习记录 + 学习者回复。"""

    updated_mission_markdown: str = Field(description="The new MISSION.md (replace, not append).")
    learning_record_title: str = Field(description="Short title of the learning record.")
    learning_record_body: str = Field(description="1-3 sentences capturing the mission shift.")
    reply: str = Field(description="A brief learner-facing message confirming the new direction.")


# --- 公开节点入口 -------------------------------------------------------------
def mission_node(state: TeachState) -> dict:
    """Mission 能力节点。按 Router 写入的 ``intent`` 选 establish / change 模式。"""
    if state.get("intent") == "mission_change":
        return _change(state)
    return _establish(state)


# --- establish 模式 -----------------------------------------------------------
def _establish(state: TeachState) -> dict:
    """访谈学习者的 WHY,据此写出 ``MISSION.md``。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    # 既有 Learner Notes 带进访谈 prompt(#022):模型看已记过什么,避免重复捕捉。首轮通常为空。
    learner_notes = workspace.read_learner_notes(directory) or ""
    system = SystemMessage(prompts.mission_establish_system(learner_notes=learner_notes))
    decide = models.get_model(
        "mission_interview", temperature=_DETERMINISTIC
    ).with_structured_output(MissionStep)

    # 访谈记录从本轮对话起步;每问一题、得一答,就把 Q/A 追加进去再决策下一步。
    transcript: list[AnyMessage] = list(state.get("messages", []))
    for _ in range(MAX_INTERVIEW_QUESTIONS):
        step: MissionStep = decide.invoke([system, *transcript])
        if step.action == "write" and step.mission_markdown:
            return _commit_mission(
                directory, step.mission_markdown, step.reply, step.language, state,
                step.learner_notes,
            )
        # 兜底问题随学习者当下语言(establish 是检测点,语言尚未持久化 → 据文本确定性判)。
        fallback_lang = language.detect_language(_last_human_text(state.get("messages", [])))
        question = step.question or language.chrome(fallback_lang)["mission_fallback_question"]
        # 暂停问学习者;resume 后整个节点从头重跑,此处直接返回学习者的回答。
        answer = interrupt({"kind": "mission_interview", "question": question})
        transcript += [AIMessage(question), HumanMessage(str(answer))]

    # 追问到上限仍未落盘 → 逼模型据现有对话现在就写出使命(兜底,极少触发)。
    final: MissionStep = decide.invoke([system, *transcript, HumanMessage(_FORCE_WRITE_NUDGE)])
    mission_markdown = final.mission_markdown or _fallback_mission(state)
    return _commit_mission(
        directory, mission_markdown, final.reply, final.language, state, final.learner_notes
    )


def _commit_mission(
    directory,
    mission_markdown: str,
    reply: str | None,
    lang: str | None,
    state: TeachState,
    learner_notes: list[CapturedNote] | None = None,
) -> dict:
    """落盘 ``MISSION.md``(一个工作区一个 Mission)+ 持久化 Workspace Language,并把
    语言码透出到状态(#020 / ADR-0013)。

    Workspace Language 「检测一次」:优先用模型在写作时顺带报出的语言码(它本就在用该
    语言写 MISSION.md,报码零额外调用);模型未给码时用确定性 ``detect_language`` 据学习者
    最近文本兜底。落盘为工作区事实(``workspace.json``),并把码写回状态 ``workspace_language``
    ——使同一轮内级联的 zpd/lesson/reference 立即读到(此刻 ``load_workspace`` 早已跑过、
    元文件尚不存在),下游不再逐节点重猜。
    """
    workspace.write_text(directory, "MISSION.md", _with_trailing_newline(mission_markdown))
    resolved = lang or language.detect_language(_last_human_text(state.get("messages", [])))
    workspace.write_workspace_language(directory, resolved)
    # 捕捉的 Learner Notes 落盘(#022 / ADR-0012):怎么写(合并/去重/落盘)由确定性原语接管。
    _capture_learner_notes(directory, learner_notes)
    # 兜底 establish 回复随刚检测出的 Workspace Language(#021),不再硬编中文。
    fallback = language.chrome(resolved)["mission_establish_reply"]
    return {
        "messages": [AIMessage(reply or fallback)],
        "workspace_language": resolved,
    }


def _fallback_mission(state: TeachState) -> str:
    """模型始终拒绝落盘时的最小合法使命(保证「先存档、不丢状态」)。"""
    why = _last_human_text(state.get("messages", [])) or "(to be refined)"
    return (
        f"# Mission: {state.get('topic', '')}\n\n"
        f"## Why\n{why}\n"
    )


# --- change 模式(P3:变更前确认,变更后更新 + 记录)--------------------------
def _change(state: TeachState) -> dict:
    """与学习者确认后,更新 ``MISSION.md`` 并追加一条 Learning Record。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    old_mission = workspace.read_text(directory, "MISSION.md") or ""
    transcript: list[AnyMessage] = list(state.get("messages", []))
    last_human = _last_human_text(transcript)
    # Workspace Language(#021 / ADR-0013):变更时语言已持久化(使命早已确立),据它令新使命
    # 正文 + 追加的 learning-record 标题/正文随语言产出,回复也据它取。缺失回退默认语言。
    lang = state.get("workspace_language") or language.detect_language(last_human)
    chrome = language.chrome(lang)

    # 1) 先确认(SKILL.md:Confirm before changing)。temp 0 → 跨重跑产出同一道
    #    问题,即便此调用被 interrupt 重跑两次也不会让 interrupt 索引错位。
    confirm_question = models.get_model("mission_interview", temperature=_DETERMINISTIC).invoke(
        [SystemMessage(prompts.mission_confirm_question_system(old_mission)), HumanMessage(last_human)]
    )
    answer = interrupt(
        {"kind": "mission_change_confirm", "question": _text(confirm_question)}
    )

    # 2) 判定是否确认(interrupt 之后,只跑一次)。未确认 → 保留原使命、不写任何文件。
    confirmation: Confirmation = models.get_model(
        "mission_interview", temperature=_DETERMINISTIC
    ).with_structured_output(Confirmation).invoke(
        [SystemMessage(prompts.mission_confirm_classify_system()), HumanMessage(str(answer))]
    )
    if not confirmation.confirmed:
        return {"messages": [AIMessage(chrome["mission_decline_reply"])]}

    # 3) 起草新使命 + 学习记录并落盘(update MISSION.md + add a learning record)。
    learner_notes = workspace.read_learner_notes(directory) or ""
    change: MissionChange = models.get_model(
        "mission_interview", temperature=_DETERMINISTIC
    ).with_structured_output(MissionChange).invoke(
        [
            SystemMessage(prompts.mission_change_system(old_mission, lang, learner_notes)),
            *transcript,
            HumanMessage(str(answer)),
        ]
    )
    workspace.write_text(
        directory, "MISSION.md", _with_trailing_newline(change.updated_mission_markdown)
    )
    _append_learning_record(directory, change.learning_record_title, change.learning_record_body)
    return {"messages": [AIMessage(change.reply or chrome["mission_change_reply"])]}


def _capture_learner_notes(directory, notes: list[CapturedNote] | None) -> None:
    """把模型捕捉到的 Learner Notes 翻译成确定性原语输入并落盘(#022 / ADR-0012)。

    何时写(捕捉到偏好/卡点/背景/疑问)是本节点的教学判断;怎么写(合并/去重/落盘)由
    ``workspace.append_learner_notes`` 接管。无捕捉项时原语返回 None、不建空文件。
    """
    if not notes:
        return
    workspace.append_learner_notes(
        directory, [workspace.LearnerNote(note.category, note.text) for note in notes]
    )


def _append_learning_record(directory, title: str, body: str) -> None:
    """按 LEARNING-RECORD-FORMAT 的命名约定追加一条记录(序号自增)。"""
    number = workspace.next_record_number(directory)
    slug = topic_slug(title) or "mission-change"
    relative = f"learning-records/{number:04d}-{slug}.md"
    workspace.write_text(directory, relative, f"# {title}\n\n{body}\n")


# --- 小工具 -------------------------------------------------------------------
def _last_human_text(messages: list[AnyMessage]) -> str:
    """取最近一条人类消息文本。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _text(message) -> str:
    """把 chat model 返回的 message 内容收敛成字符串(content 可能是 list)。"""
    content = getattr(message, "content", message)
    return content if isinstance(content, str) else str(content)


def _with_trailing_newline(text: str) -> str:
    """确保文本以换行结尾(产物落盘整洁;模型有时省略末尾换行)。"""
    return text if text.endswith("\n") else text + "\n"


__all__ = ["mission_node", "MissionStep", "Confirmation", "MissionChange"]
