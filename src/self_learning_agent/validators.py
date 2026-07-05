"""Lesson 质量门的**确定性机器校验器**(纯函数,不调 LLM)。

ADR-0006 的核心工程纪律:课程质量由**架构**保证,而非寄望模型一次写好。
其中一半是「LLM 对照 RUBRIC 自审」(在 Lesson 子图 #007 里),另一半——也是把
「课程质量」从概率变保证的关键——是这组**确定性校验**:RUBRIC.md 里凡标
*(Deterministic)* 的条目,都由代码 pass/fail,**不**交给 judge。任一确定性条目
失败即整课失败(RUBRIC「Pass threshold」:All deterministic items MUST pass 100%)。

覆盖的 RUBRIC 条目(见 RUBRIC.md Part 1):

- ``html_parseable``      —— 课程是一份可解析、标签良构的自包含 HTML(子图门的基本前提)。
- ``links_reachable``     —— 内部锚点(``#frag`` → 文档内 id)与本地资源/跨文档链接
                              (相对路径 → 工作区内真实文件)可达。**不**校验外链网络可达
                              (那是 L6 的职责,且确定性校验绝不触网)。
- ``L6_citations``        —— 课程里每个外链引用都能在 ``RESOURCES.md`` 找到
                              (SKILL.md §Knowledge:95「Lessons should be littered with citations」)。
- ``L7_primary_source``   —— 推荐了一个最高质量一手资源(present/absent)
                              (SKILL.md §Lessons:59)。
- ``L9_quiz_no_length_tell``—— 测验不通过选项长度泄露答案:被标记的正确项不得在长度上
                              「鹤立鸡群」(SKILL.md §Skills:110;严格等长作创作引导,见函数注释)。
- ``L12_cross_doc_links`` —— 含指向其他课程 / 参考文档的 HTML 锚点(present/absent)
                              (SKILL.md §Lessons:57)。
- ``L13_ask_agent``       —— 含「可向智能体追问」的提醒(present/absent)
                              (SKILL.md §Lessons:61)。
- ``L17_glossary``        —— 术语与 ``GLOSSARY.md`` 一致(可程序比较处:不使用被
                              ``_Avoid_:`` 列为禁用别名的词)(GLOSSARY-FORMAT.md:32)。

**HTML 约定(本 issue 定义,Lesson 子图 #007 遵循 / 本模块检测)**:
RUBRIC 的若干 present/absent 条目(L7、L13)与分组条目(L9)需要一个**可程序检测的
标记**,原 ``teach`` skill 由人/模型肉眼判断,移植成独立确定性门后必须有明确契约。
故在此把契约定为一组 HTML 属性 / class(见下方 ``MARKER_*`` / ``QUIZ_*`` 常量),
一处定义、两处复用(#007 产出、本模块校验、测试夹具)。这是 ``[ours]`` 的脚手架,
不改动 RUBRIC 任何 *verbatim* 文字,只是把「present/absent」落成可判定的机器信号。

零新依赖:用标准库 ``html.parser`` 解析。每个 ``check_*`` 是 ``(html, ...) -> CheckResult``
的纯函数,可对 HTML fixture 直接单测;``validate_lesson`` 把它们汇总成质量门结果,
供 Lesson 子图(#007)消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# --- HTML 约定常量(#007 产出 / 本模块校验 / 测试共享)------------------------
# 一手资源推荐(L7):带 ``data-primary-source`` 属性,或 class 含 ``primary-source``。
MARKER_PRIMARY_SOURCE_ATTR = "data-primary-source"
MARKER_PRIMARY_SOURCE_CLASS = "primary-source"
# 「可向智能体追问」提醒(L13):带 ``data-ask-agent`` 属性,或 class 含 ``ask-agent``。
MARKER_ASK_AGENT_ATTR = "data-ask-agent"
MARKER_ASK_AGENT_CLASS = "ask-agent"
# 测验分组(L9):容器带 ``data-quiz`` / class ``quiz``;选项带 ``data-quiz-option`` /
# class ``quiz-option``;正确选项额外带 ``data-correct`` / class ``correct``
# (正确项标记是 ADR-0002 课内 JS 即时判分本就需要的,L9 复用它判定「答案是否因长度突出」)。
QUIZ_CONTAINER_ATTR = "data-quiz"
QUIZ_CONTAINER_CLASS = "quiz"
QUIZ_OPTION_ATTR = "data-quiz-option"
QUIZ_OPTION_CLASS = "quiz-option"
QUIZ_CORRECT_ATTR = "data-correct"
QUIZ_CORRECT_CLASS = "correct"
# 技能型课(#017 / §D6):<body> 带 ``data-skill-lesson`` → 该课须含 worked example 或
# 动手任务(check_skill_lesson_has_practice)。worked example 区带 ``data-worked-example``;
# 动手任务区带 ``data-practice-task``,其自检预期结果带 ``data-practice-expected``。
MARKER_SKILL_LESSON_ATTR = "data-skill-lesson"
MARKER_WORKED_EXAMPLE_ATTR = "data-worked-example"
MARKER_PRACTICE_TASK_ATTR = "data-practice-task"
MARKER_PRACTICE_EXPECTED_ATTR = "data-practice-expected"

# HTML 空元素(无结束标签),良构检查时不压栈。
_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# 这些元素的文本内容不计入「可见文本」(L17 术语比较用),且其中是脚本/样式而非散文。
_SKIP_TEXT_ELEMENTS = {"script", "style"}

# 带这些 scheme 的链接是「外部 / 非文件」链接,不参与本地可达性校验。
_NON_FILE_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:", "javascript:")

# 从 markdown(RESOURCES.md)里抓 http(s) URL。
_URL_IN_TEXT = re.compile(r"https?://[^\s)\]<>\"']+")
# GLOSSARY.md 里的禁用别名行:``_Avoid_: alias1, alias2``(GLOSSARY-FORMAT.md 示例)。
_AVOID_LINE = re.compile(r"_Avoid_:\s*(.+)", re.IGNORECASE)


@dataclass(frozen=True)
class CheckResult:
    """单条确定性校验的结果。``name`` 用 RUBRIC 条目号便于回溯;``detail`` 在 fail 时给原因。"""

    name: str
    passed: bool
    detail: str = ""


# === HTML 解析(一次解析,多项复用)===========================================
@dataclass
class _Frame:
    """标签栈的一帧。记录该元素是否开启了一个 quiz 组 / 是否本身是一个 quiz 选项。"""

    tag: str
    quiz_id: int | None = None          # 非空:本元素是一个 quiz 容器,值为组号
    option_of: int | None = None        # 非空:本元素是一个 quiz 选项,值为所属组号
    option_correct: bool = False        # 本选项是否被标记为正确(L9 据此判断长度泄露)
    option_buffer: list[str] = field(default_factory=list)
    skips_text: bool = False            # 本元素是 script/style,内部文本不计入可见文本


class _LessonDocument(HTMLParser):
    """把课程 HTML 解析成校验所需的结构化视图(链接 / 资源 / id / 文本 / 标记 / 测验 / 良构)。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchor_hrefs: list[str] = []       # 所有 <a href>
        self.asset_refs: list[str] = []         # img/script/link/source/... 的 src/href
        self.ids: set[str] = set()              # 所有 id(供 #frag 内部锚点解析)
        self.has_primary_source = False         # L7 标记是否出现
        self.has_ask_agent = False              # L13 标记是否出现
        self.has_skill_lesson = False           # #017:技能型课标记是否出现
        self.has_worked_example = False         # #017:worked example 区是否出现
        self.has_practice_task = False          # #017:动手任务区是否出现
        self.has_practice_expected = False      # #017:动手任务自检预期结果是否出现
        self.quizzes: dict[int, list[tuple[str, bool]]] = {}  # 组号 -> [(选项规范化文本, 是否正确)](L9)
        self.errors: list[str] = []             # 良构错误(标签不匹配 / 未闭合)
        self._text_parts: list[str] = []
        self._stack: list[_Frame] = []
        self._quiz_seq = 0
        self._skip_text_depth = 0

    # --- 提取属性副作用(start 与自闭合标签共用)---
    def _record_attrs(self, tag: str, attrs: dict[str, str], classes: set[str]) -> None:
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.anchor_hrefs.append(attrs["href"])
        if tag in {"img", "script", "source", "audio", "video", "iframe", "track"} and attrs.get("src"):
            self.asset_refs.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            self.asset_refs.append(attrs["href"])
        if MARKER_PRIMARY_SOURCE_ATTR in attrs or MARKER_PRIMARY_SOURCE_CLASS in classes:
            self.has_primary_source = True
        if MARKER_ASK_AGENT_ATTR in attrs or MARKER_ASK_AGENT_CLASS in classes:
            self.has_ask_agent = True
        if MARKER_SKILL_LESSON_ATTR in attrs:
            self.has_skill_lesson = True
        if MARKER_WORKED_EXAMPLE_ATTR in attrs:
            self.has_worked_example = True
        if MARKER_PRACTICE_TASK_ATTR in attrs:
            self.has_practice_task = True
        if MARKER_PRACTICE_EXPECTED_ATTR in attrs:
            self.has_practice_expected = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        adict = {name: (value or "") for name, value in attrs}
        classes = set(adict.get("class", "").split())
        self._record_attrs(tag, adict, classes)

        frame = _Frame(tag=tag)
        if QUIZ_CONTAINER_ATTR in adict or QUIZ_CONTAINER_CLASS in classes:
            self._quiz_seq += 1
            frame.quiz_id = self._quiz_seq
            self.quizzes.setdefault(self._quiz_seq, [])
        if QUIZ_OPTION_ATTR in adict or QUIZ_OPTION_CLASS in classes:
            group = self._current_quiz_id()
            if group is None:  # 散落的选项(无容器)归入组 0,仍能彼此比较
                group = 0
                self.quizzes.setdefault(0, [])
            frame.option_of = group
            frame.option_correct = QUIZ_CORRECT_ATTR in adict or QUIZ_CORRECT_CLASS in classes
        if tag in _SKIP_TEXT_ELEMENTS:
            frame.skips_text = True
            self._skip_text_depth += 1

        if tag not in _VOID_ELEMENTS:
            self._stack.append(frame)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 自闭合 <tag/>:只记录属性副作用,不压栈、不开启捕获区(无内容)。
        adict = {name: (value or "") for name, value in attrs}
        classes = set(adict.get("class", "").split())
        self._record_attrs(tag, adict, classes)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        if self._stack and self._stack[-1].tag == tag:
            self._finalize(self._stack.pop())
            return
        # 不匹配:记一个良构错误。尝试回退到最近的同名标签以维持后续捕获的合理性
        # (确定性校验只需知道「存在错误」;不可解析的 fixture 由 html_parseable 判 fail,
        # 其余校验不会对该 fixture 断言)。
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                self.errors.append(f"mismatched </{tag}>")
                for frame in reversed(self._stack[index:]):
                    self._finalize(frame)
                del self._stack[index:]
                return
        self.errors.append(f"stray </{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_text_depth:
            return
        option = self._capturing_option()
        if option is not None:
            option.option_buffer.append(data)
        self._text_parts.append(data)

    def _finalize(self, frame: _Frame) -> None:
        if frame.skips_text and self._skip_text_depth:
            self._skip_text_depth -= 1
        if frame.option_of is not None:
            self.quizzes[frame.option_of].append(
                (_normalize_ws("".join(frame.option_buffer)), frame.option_correct)
            )

    def _current_quiz_id(self) -> int | None:
        for frame in reversed(self._stack):
            if frame.quiz_id is not None:
                return frame.quiz_id
        return None

    def _capturing_option(self) -> _Frame | None:
        for frame in reversed(self._stack):
            if frame.option_of is not None:
                return frame
        return None

    @property
    def visible_text(self) -> str:
        return _normalize_ws("".join(self._text_parts))


def _parse(html: str) -> _LessonDocument:
    """解析课程 HTML,并把「文档结束时仍未闭合的标签」补记为良构错误。"""
    document = _LessonDocument()
    document.feed(html)
    document.close()
    for frame in document._stack:
        document.errors.append(f"unclosed <{frame.tag}>")
    return document


def _normalize_ws(text: str) -> str:
    """折叠所有空白为单空格并去首尾(等长比较、术语比较的规范化基准)。"""
    return " ".join(text.split())


# === 确定性校验(每个都是纯函数,可对 HTML fixture 直接单测)==================
def check_html_parseable(html: str) -> CheckResult:
    """HTML 可解析且标签良构(无不匹配 / 未闭合标签)。Lesson 子图门的基本前提。"""
    document = _parse(html)
    if document.errors:
        return CheckResult("html_parseable", False, "; ".join(document.errors[:5]))
    return CheckResult("html_parseable", True)


def local_link_reachable(ref: str, base_dir: str | Path) -> bool | None:
    """一个链接的**本地文件可达性**(确定性,不触网)。可达性判定的**单一定义**——
    ``check_links_reachable``(质量门)与 Lesson 子图渲染前的 cross_link 过滤共用它,
    避免两处对「什么算可达」各写一份而漂移。

    返回:
    - ``None``:该链接不是本地文件引用(外链 / 非文件 scheme / 协议相对 ``//`` / 纯
      文档内 ``#frag`` / 空),**无本地文件可查**——调用方按各自语义处理(门跳过、过滤保留)。
    - ``True``:相对 ``base_dir`` 解析后的目标文件在磁盘上存在。
    - ``False``:目标是本地文件但**不存在**。
    """
    ref = ref.strip()
    if not ref or ref.startswith("#"):
        return None
    # 外部 / 非文件 scheme,以及协议相对 ``//host/...`` → 非本地文件引用。
    if ref.lower().startswith(_NON_FILE_SCHEMES) or ref.startswith("//"):
        return None
    local = ref.split("#", 1)[0].split("?", 1)[0]
    if not local:
        return None
    return (Path(base_dir) / local).exists()


def check_links_reachable(html: str, lesson_path: str | Path) -> CheckResult:
    """内部锚点与本地资源/跨文档链接可达(确定性,不触网)。

    - 内部锚点 ``#frag``:其 ``frag`` 必须匹配文档内某个 ``id``。
    - 本地相对链接(资源 / 跨文档,如 ``./assets/x.css``、``../lessons/y.html``):
      相对 ``lesson_path`` 所在目录解析后必须是工作区里真实存在的文件(``local_link_reachable``)。
    - 外链(http/https/mailto/tel/...):**不**在此校验(L6 负责外链引用;确定性校验绝不触网)。
    """
    document = _parse(html)
    base_dir = Path(lesson_path).resolve().parent
    broken: list[str] = []
    for ref in document.anchor_hrefs + document.asset_refs:
        ref = ref.strip()
        if ref.startswith("#"):
            if ref[1:] not in document.ids:
                broken.append(ref)
            continue
        # 本地文件引用不存在 → 不可达;None(外链等)与 True(存在)均放过(不触网)。
        if local_link_reachable(ref, base_dir) is False:
            broken.append(ref)
    if broken:
        return CheckResult("links_reachable", False, f"unreachable: {broken}")
    return CheckResult("links_reachable", True)


def check_citations_in_resources(html: str, resources_md: str) -> CheckResult:
    """L6(确定性半):课程里的每个外链引用都能在 ``RESOURCES.md`` 找到。

    L6 的「为每个论断配引用」属判断(无法由代码数论断);此处只强制其确定性半——
    凡课程引用的外链 URL,都必须出现在 ``RESOURCES.md``(承接 P1「Never trust your
    parametric knowledge」:知识只能源自已甄别的高信任资源)。课程无外链时空真通过。
    """
    resource_urls = {_normalize_url(url) for url in _URL_IN_TEXT.findall(resources_md or "")}
    document = _parse(html)
    missing: list[str] = []
    for href in document.anchor_hrefs:
        href = href.strip()
        if href.lower().startswith(("http://", "https://")):
            if _normalize_url(href) not in resource_urls:
                missing.append(href)
    if missing:
        return CheckResult("L6_citations", False, f"not in RESOURCES.md: {missing}")
    return CheckResult("L6_citations", True)


def check_primary_source(html: str) -> CheckResult:
    """L7(present/absent):课程推荐了一个最高质量一手资源(带约定标记)。"""
    document = _parse(html)
    if document.has_primary_source:
        return CheckResult("L7_primary_source", True)
    return CheckResult(
        "L7_primary_source",
        False,
        f"missing marker [{MARKER_PRIMARY_SOURCE_ATTR} / .{MARKER_PRIMARY_SOURCE_CLASS}]",
    )


# L9「无长度泄露」判定参数([ours],可调)。仅当正确项在长度上「鹤立鸡群」——
# 既显著长于/短于所有干扰项(比例 ≥ _LENGTH_TELL_RATIO)、又超过一个绝对字数地板
# (_LENGTH_TELL_FLOOR)——才判为格式泄露。容差刻意给得宽:把「严格等长」留作创作
# 引导(承接 SKILL.md §Skills:110 的 verbatim 文字,写进 #007 起草提示),不在确定性门
# 上强行抠等长而牺牲选项的语义一致性与表达力(语义 > 等长)。
_LENGTH_TELL_RATIO = 1.4
_LENGTH_TELL_FLOOR = 4


def check_quiz_no_length_tell(html: str) -> CheckResult:
    """L9:测验不通过选项长度泄露答案。

    承接 SKILL.md §Skills:110 [verbatim]「Don't give the user any clues about the answer
    through formatting」。**[ours] 取舍(语义优先)**:原文「each answer should be exactly
    the same number of words」是给作者的等长**引导**;若把它落成「严格等长」的硬门,会逼
    模型为凑长度扭曲选项语义。故确定性门只守原文真正的目的——**正确项不因长度突出**:
    仅当被标记的正确项显著长于或短于**所有**干扰项(超过 _LENGTH_TELL_* 容差)时判 fail。
    选项间自然的长度差异被允许,语义一致性与表达力优先;严格等长仍作为创作引导写进起草
    提示,细粒度的等长打磨交给自审 / 人评判断层。长度以**字符数**衡量(视觉长度的语言无关代理)。

    跳过的情形:选项 < 3(如判断题,长度差不构成有意义的 tell);无唯一标记的正确项
    (无从判断「答案是否因长度突出」)。
    """
    document = _parse(html)
    for group_id, options in document.quizzes.items():
        if len(options) < 3:
            continue
        correct = [text for text, is_correct in options if is_correct]
        if len(correct) != 1:
            continue
        correct_len = len(correct[0])
        distractors = [len(text) for text, is_correct in options if not is_correct]
        longest, shortest = max(distractors), min(distractors)
        too_long = (
            correct_len - longest >= _LENGTH_TELL_FLOOR
            and correct_len >= longest * _LENGTH_TELL_RATIO
        )
        too_short = (
            shortest - correct_len >= _LENGTH_TELL_FLOOR
            and shortest >= correct_len * _LENGTH_TELL_RATIO
        )
        if too_long or too_short:
            side = "longest" if too_long else "shortest"
            return CheckResult(
                "L9_quiz_no_length_tell",
                False,
                f"quiz {group_id}: correct option is a length {side} outlier "
                f"(correct={correct_len}, distractors={distractors})",
            )
    return CheckResult("L9_quiz_no_length_tell", True)


def check_cross_doc_anchors(html: str) -> CheckResult:
    """L12(present/absent):含至少一个指向其他课程 / 参考文档的 HTML 锚点(本地 ``.html`` 链接)。"""
    document = _parse(html)
    for href in document.anchor_hrefs:
        href = href.strip()
        lowered = href.lower()
        if lowered.startswith(("http://", "https://")) or href.startswith("#"):
            continue
        target = lowered.split("#", 1)[0].split("?", 1)[0]
        if target.endswith(".html"):
            return CheckResult("L12_cross_doc_links", True)
    return CheckResult("L12_cross_doc_links", False, "no local .html anchor to a lesson/reference")


def check_ask_agent_reminder(html: str) -> CheckResult:
    """L13(present/absent):含「可向智能体追问」的提醒(带约定标记)。"""
    document = _parse(html)
    if document.has_ask_agent:
        return CheckResult("L13_ask_agent", True)
    return CheckResult(
        "L13_ask_agent",
        False,
        f"missing marker [{MARKER_ASK_AGENT_ATTR} / .{MARKER_ASK_AGENT_CLASS}]",
    )


def check_glossary_adherence(html: str, glossary_md: str) -> CheckResult:
    """L17(确定性半):课程不使用 ``GLOSSARY.md`` 中被 ``_Avoid_:`` 列为禁用的别名。

    承接 GLOSSARY-FORMAT.md:32 [verbatim]「Once a term is in the glossary, prefer it
    everywhere」与「pick the best one and list the rest as aliases to avoid」。可程序比较
    的确定性半:词汇表里每个 ``_Avoid_:`` 别名都不应在课程可见文本里出现。ASCII 别名用
    词边界匹配避免误伤(如别名 ``set`` 不应命中 ``settings``);非 ASCII(中文)别名用子串匹配。
    """
    avoided: list[str] = []
    for line in (glossary_md or "").splitlines():
        match = _AVOID_LINE.search(line)
        if match:
            for alias in match.group(1).split(","):
                alias = alias.strip()
                if alias:
                    avoided.append(alias)
    if not avoided:
        return CheckResult("L17_glossary", True)

    text = _parse(html).visible_text
    lowered_text = text.lower()
    violations: list[str] = []
    for alias in avoided:
        lowered_alias = alias.lower()
        if alias.isascii():
            if re.search(rf"\b{re.escape(lowered_alias)}\b", lowered_text):
                violations.append(alias)
        elif lowered_alias in lowered_text:
            violations.append(alias)
    if violations:
        return CheckResult("L17_glossary", False, f"uses avoided aliases: {violations}")
    return CheckResult("L17_glossary", True)


def check_skill_lesson_has_practice(html: str) -> CheckResult:
    """#017(§D6):技能型课(带 ``data-skill-lesson``)须含 worked example 或动手任务。

    [ours] 脚手架,抬高技能型课的结构质量天花板(承接 §Skills 的紧反馈闭环):只在课程
    自称技能型时才要求,否则空真通过(知识型课不强加)。技能型课缺二者时判 fail,回起草
    步带原因重写(ADR-0006)。
    """
    document = _parse(html)
    if not document.has_skill_lesson:
        return CheckResult("skill_lesson_practice", True)
    if document.has_worked_example or document.has_practice_task:
        return CheckResult("skill_lesson_practice", True)
    return CheckResult(
        "skill_lesson_practice",
        False,
        "skill lesson must include a worked example or a hands-on practice task "
        f"(missing [{MARKER_WORKED_EXAMPLE_ATTR}] and [{MARKER_PRACTICE_TASK_ATTR}])",
    )


def check_practice_task_has_expected(html: str) -> CheckResult:
    """#017(§D6):动手任务(带 ``data-practice-task``)须带自检预期结果(可判)。

    紧反馈闭环要能当场自检 → 任务必须给出预期结果(``data-practice-expected``);无任务时
    空真通过。守渲染契约(确定性,defense in depth)。
    """
    document = _parse(html)
    if not document.has_practice_task:
        return CheckResult("practice_task_expected", True)
    if document.has_practice_expected:
        return CheckResult("practice_task_expected", True)
    return CheckResult(
        "practice_task_expected",
        False,
        f"practice task must include a self-checkable expected result "
        f"(missing [{MARKER_PRACTICE_EXPECTED_ATTR}])",
    )


def _normalize_url(url: str) -> str:
    """URL 规范化:去首尾空白、去 fragment、去末尾斜杠(等价比较用)。"""
    return url.strip().split("#", 1)[0].rstrip("/")


# === 质量门汇总 ===============================================================
def validate_lesson(
    html: str,
    *,
    lesson_path: str | Path,
    resources_md: str = "",
    glossary_md: str = "",
) -> list[CheckResult]:
    """对一节课程跑全部确定性校验,返回结果列表(顺序稳定)。

    供 Lesson 子图(#007)作质量门消费:用 ``all_passed`` 判定;任一 fail 则整课不达标,
    回到起草步重写(ADR-0006),重试耗尽则不交付(ADR-0009 失败姿态)。
    """
    return [
        check_html_parseable(html),
        check_links_reachable(html, lesson_path),
        check_citations_in_resources(html, resources_md),
        check_primary_source(html),
        check_quiz_no_length_tell(html),
        check_cross_doc_anchors(html),
        check_ask_agent_reminder(html),
        check_glossary_adherence(html, glossary_md),
        check_skill_lesson_has_practice(html),
        check_practice_task_has_expected(html),
    ]


def all_passed(results: list[CheckResult]) -> bool:
    """全部确定性条目通过(RUBRIC「All deterministic items MUST pass 100%」)。"""
    return all(result.passed for result in results)


__all__ = [
    "CheckResult",
    "check_html_parseable",
    "local_link_reachable",
    "check_links_reachable",
    "check_citations_in_resources",
    "check_primary_source",
    "check_quiz_no_length_tell",
    "check_cross_doc_anchors",
    "check_ask_agent_reminder",
    "check_glossary_adherence",
    "check_skill_lesson_has_practice",
    "check_practice_task_has_expected",
    "validate_lesson",
    "all_passed",
    "MARKER_SKILL_LESSON_ATTR",
    "MARKER_WORKED_EXAMPLE_ATTR",
    "MARKER_PRACTICE_TASK_ATTR",
    "MARKER_PRACTICE_EXPECTED_ATTR",
    "MARKER_PRIMARY_SOURCE_ATTR",
    "MARKER_PRIMARY_SOURCE_CLASS",
    "MARKER_ASK_AGENT_ATTR",
    "MARKER_ASK_AGENT_CLASS",
    "QUIZ_CONTAINER_ATTR",
    "QUIZ_CONTAINER_CLASS",
    "QUIZ_OPTION_ATTR",
    "QUIZ_OPTION_CLASS",
    "QUIZ_CORRECT_ATTR",
    "QUIZ_CORRECT_CLASS",
]
