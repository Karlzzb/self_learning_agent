"""Lesson 创作子图(ADR-0006 / #007):起草 → 机器校验 → LLM 自审 → 不达标则重写。

ADR-0006 的核心工程纪律:**课程质量由架构保证,而非寄望模型一次写好**。一节课不是
一次 LLM 调用,而是一张子图:

    draft(强模型,据 scope + 资源 + 已有组件产出结构化内容)
      → render(确定性渲染成 self-contained HTML:共享设计系统 + 内置判分 JS + 约定 marker)
      → validate(#006 确定性机器校验,纯函数,不调 LLM)
      → 确定性条目全过? ── 否 ──→ revise(回到 draft;带上失败原因)
            │是
      → critique(LLM 对照权威 RUBRIC.md 给判断条目打分)
      → 达标(每项 ≥3 且均值 ≥4.0)? ── 否 ──→ revise
            │是
      → commit(落盘课程 HTML,更新课程索引)

**重试有上限 + 兜底(ADR-0009 失败姿态)**:重写达 ``config.LESSON_MAX_ATTEMPTS`` 仍不
达标 → **不交付未达标版**,只回一条「请稍后再来」;不写课程 HTML。状态不丢:本节点正常
返回,父图照常走到 finalize,checkpointer 完成存档,学习者下次回来可无损续接。

**生成策略 = 共享设计系统 + assets 组件库(ADR-0006 / §Assets)**:
- 共享样式表 ``assets/lesson.css`` 是「每个工作区挣到的第一个组件」,由本模块**确定性**
  写入(它是代码拥有的设计 token 表,不由模型起草),每节课都链接它 → 所有课程看起来
  像一门连贯的课程。
- 课程索引 ``lessons/index.html`` 由本模块确定性维护:既给每节课一个**保证可达**的本地
  ``.html`` 锚点(满足 L12 + 链接可达),又是一个真实有用的课程目录。
- 模型只产**结构化内容**(标题、正文块、引用、一手资源、测验、追问提醒、跨课链接、需要
  的新组件),由确定性渲染器拼成 HTML——这样 #006 的确定性条目(引用都在 RESOURCES、
  L7/L13 marker present、测验等长、锚点可达)由**架构**保证,不靠模型自律。

**课内反馈(ADR-0002 i)**:渲染器为测验注入内置 JS,点击选项即时判分(课程保持静态、
可移植,脱离后端仍能打开)。判分依据是选项上的 ``data-correct`` 标记——这正是 #006 的
L9 校验所读的同一个标记(一处定义,多处复用)。

子图**无 interrupt**(课内对话式评估是 #008 的职责),故编译为**无 checkpointer** 的纯
计算+IO 单元,由父图节点 ``lesson_node`` 在单轮内直接 ``invoke``。
"""

from __future__ import annotations

import html as _html_lib
import json as _json
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from . import config, language, models, prompts, scoring, validators, workspace
from .state import TeachState
from .tenancy import topic_slug
from .workspace import workspace_dir

# 共享样式表 / 课程索引的固定相对路径(代码拥有,确定性维护)。
SHARED_STYLESHEET = "assets/lesson.css"
LESSONS_INDEX = "lessons/index.html"

# 暂缓 / commit 的学习者可见回复由 Workspace Language 从 chrome 常量表取(#021 / ADR-0013),
# 不再硬编中文:这些是确定性回复(commit)/ 兜底(defer),随持久化语言产出。


def _defer_reply(lang: str) -> str:
    """暂缓时给学习者的兜底回复(随 Workspace Language,保证「请稍后再来」永不为空)。"""
    return language.chrome(lang)["lesson_defer_reply"]


# =============================================================================
# 结构化输出 schema(模型只产这些;HTML 渲染 / 文件写入由确定性代码接管)
# =============================================================================
class Citation(BaseModel):
    """一条引用:论断 + 背书它的外链(URL 必须来自 RESOURCES.md,L6)。"""

    claim_text: str = Field(description="The claim being made in the lesson.")
    url: str = Field(description="Backing URL, taken from RESOURCES.md. Never invented.")


class PrimarySource(BaseModel):
    """一手资源推荐(L7):最高质量、最可信的一个来源。"""

    label: str = Field(description="Human-readable label, e.g. 'Book: Deep Learning'.")
    url: str = Field(description="URL from RESOURCES.md.")


class QuizOption(BaseModel):
    """测验的一个选项。``correct`` 既驱动课内 JS 判分,又是 #006 L9 校验读的标记。"""

    text: str = Field(description="Option text. Keep options the same length; no tell.")
    correct: bool = Field(description="True for exactly one option.")


class Quiz(BaseModel):
    """一道检索练习题(必要难度:retrieval practice)。"""

    question: str = Field(description="The retrieval-practice question.")
    options: list[QuizOption] = Field(description="One correct option and >=2 distractors.")


class Block(BaseModel):
    """课程正文的一个块(先讲知识,再练技能;L15)。"""

    kind: Literal["heading", "prose"] = Field(description="'heading' or 'prose'.")
    text: str = Field(description="Block text.")


class CrossLink(BaseModel):
    """指向其他课程 / 参考文档的锚点(L12)。``href`` 为相对 ``.html`` 路径。"""

    label: str = Field(description="Link label.")
    href: str = Field(description="Relative .html path, e.g. './0001-intro.html'.")


class NewComponent(BaseModel):
    """本课需要、但 ``assets/`` 尚无的可复用组件(§Assets:reuse is the default)。"""

    filename: str = Field(description="Filename under assets/, e.g. 'diagram.css'.")
    content: str = Field(description="The component's full content.")


class ExampleAnnotation(BaseModel):
    """worked-example 里对某一步 / 某一行代码的「为什么」注解(#017 / §D6)。"""

    step_or_line: str = Field(description="The step or code line/parameter being explained.")
    why: str = Field(description="Why this step/parameter — the reasoning, not just what it does.")


class WorkedExample(BaseModel):
    """一个可运行示例 + 逐步/逐参数注解(#017 / §D6:抬结构质量天花板)。

    技能型课不该把代码硬塞进 prose;这里给代码一个独立结构位,配「为什么」注解 + 一句
    takeaway,由确定性渲染器拼成带 marker 的代码块(承接 §Knowledge/§Skills)。
    """

    language: str = Field(description="Code language, e.g. 'python' (for display only).")
    code: str = Field(description="The runnable example code.")
    annotations: list[ExampleAnnotation] = Field(
        default_factory=list, description="Step-by-step / per-parameter 'why' annotations."
    )
    takeaway: str = Field(description="One sentence: the key thing this example teaches.")


class PracticeTask(BaseModel):
    """动手任务 + 即时自检(#017 / §D6:紧反馈闭环,承接 §Skills)。

    ``expected_result`` 让学习者当场判断自己做对没有(自检可判),是紧反馈闭环的核心;
    ``hint`` 可选,给卡住的学习者一个台阶。
    """

    instructions: str = Field(description="What the learner should do, hands-on.")
    expected_result: str = Field(
        description="The concrete result the learner should get, so they can self-check."
    )
    hint: str | None = Field(default=None, description="Optional hint if they get stuck.")


class LessonDraft(BaseModel):
    """Lesson 子图起草步的结构化产物(渲染器据此拼出 HTML)。"""

    title: str = Field(description="Human-readable lesson title (the one scoped thing).")
    body_blocks: list[Block] = Field(description="Knowledge first, before practice.")
    # 技能型课标记(#017 / §D6):模型判断这节课是否教一项技能/技法,值得配 worked
    # example 或动手任务。为真时确定性校验要求至少有其一(check_skill_lesson_has_practice)。
    is_skill_lesson: bool = Field(
        default=False,
        description="True if this lesson teaches a skill/technique that warrants a worked example or hands-on task.",
    )
    worked_example: WorkedExample | None = Field(
        default=None, description="A runnable example with step-by-step 'why' annotations (#017)."
    )
    practice_task: PracticeTask | None = Field(
        default=None, description="A hands-on task with an expected result for self-check (#017)."
    )
    citations: list[Citation] = Field(
        default_factory=list, description="Every claim backed by a RESOURCES.md URL (L6)."
    )
    primary_source: PrimarySource = Field(description="The one highest-quality source (L7).")
    quiz: Quiz = Field(description="A retrieval-practice quiz with immediate feedback (L8/L9).")
    ask_agent_reminder: str = Field(description="Reminder the learner can ask the teacher (L13).")
    cross_links: list[CrossLink] = Field(
        default_factory=list, description="Anchor links to other lessons/reference docs (L12)."
    )
    new_components: list[NewComponent] = Field(
        default_factory=list, description="New reusable components for assets/ (empty if none)."
    )


class CritiqueItem(BaseModel):
    """自审对 RUBRIC 一个**判断**条目的打分(确定性条目不在此打分)。"""

    id: str = Field(description="Rubric item id, e.g. 'L1'.")
    score: int = Field(description="Integer 1-5.")
    justification: str = Field(description="One line explaining the score.")


class LessonCritique(BaseModel):
    """Lesson 子图自审步的结构化产物(对照 RUBRIC.md 判断条目)。"""

    items: list[CritiqueItem] = Field(description="One entry per judgement item scored.")


# =============================================================================
# 确定性渲染(共享设计系统 + 内置判分 JS + 约定 marker)——纯函数,不调 LLM
# =============================================================================
# 共享设计系统:一份 CSS token 表(Tufte 风格:衬线、窄栏、留白、克制配色)。
# 这是「每个工作区挣到的第一个组件」,代码拥有、确定性写入,所有课程链接它,使课程
# 看起来像一门连贯的课程(§Assets / L10 / L11)。
_SHARED_CSS = """\
:root {
  --ink: #1a1a1a;
  --muted: #6b6b6b;
  --rule: #d8d2c4;
  --accent: #7a1f1f;
  --bg: #fffef9;
  --ok: #1f5f3a;
  --bad: #7a1f1f;
  --measure: 38rem;
}
* { box-sizing: border-box; }
body {
  margin: 0 auto;
  padding: 3rem 1.5rem 5rem;
  max-width: var(--measure);
  font-family: Georgia, 'Iowan Old Style', 'Songti SC', serif;
  font-size: 1.0625rem;
  line-height: 1.65;
  color: var(--ink);
  background: var(--bg);
}
h1, h2, h3 { line-height: 1.2; font-weight: 600; }
h1 { font-size: 1.9rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.3rem; margin: 2.25rem 0 0.5rem; }
.subtitle { color: var(--muted); margin: 0 0 2rem; font-style: italic; }
p { margin: 0 0 1rem; }
a { color: var(--accent); }
hr { border: none; border-top: 1px solid var(--rule); margin: 2.5rem 0; }
sup a { text-decoration: none; }
.citations { font-size: 0.875rem; color: var(--muted); }
.citations li { margin-bottom: 0.35rem; }
.primary-source {
  border-left: 3px solid var(--accent);
  padding: 0.75rem 1rem;
  margin: 1.5rem 0;
  background: #faf6ec;
}
.quiz {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 1.25rem 1.25rem 0.5rem;
  margin: 2rem 0;
}
.quiz-option {
  display: block;
  width: 100%;
  text-align: left;
  font: inherit;
  margin: 0.4rem 0;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--rule);
  border-radius: 5px;
  background: #fff;
  cursor: pointer;
}
.quiz-option.is-correct { border-color: var(--ok); background: #eef7f0; }
.quiz-option.is-wrong { border-color: var(--bad); background: #f9eeee; }
.quiz-feedback { min-height: 1.5rem; margin: 0.75rem 0 0.5rem; font-size: 0.9375rem; }
.ask-agent {
  margin: 2.5rem 0 0;
  padding: 0.9rem 1.1rem;
  background: #f3f0e7;
  border-radius: 6px;
  font-size: 0.9375rem;
}
.crosslinks { font-size: 0.9375rem; }
.worked-example {
  margin: 2rem 0;
  padding: 1rem 1.25rem;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: #fbf9f2;
}
.worked-example pre.code {
  overflow-x: auto;
  padding: 0.9rem 1rem;
  background: #1a1a1a;
  color: #f5f2e9;
  border-radius: 5px;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}
.worked-example pre.code code { font-family: inherit; }
.worked-example .annotations { font-size: 0.9375rem; margin: 1rem 0; }
.worked-example .annotations li { margin-bottom: 0.4rem; }
.worked-example .takeaway { margin: 0.75rem 0 0; }
.practice-task {
  margin: 2rem 0;
  padding: 1rem 1.25rem;
  border-left: 3px solid var(--ok);
  background: #eef7f0;
  border-radius: 6px;
}
.practice-task .expected { margin: 0.75rem 0 0; font-size: 0.9375rem; }
.practice-task .hint { margin: 0.75rem 0 0; font-size: 0.9375rem; }
"""

# 课内即时判分 JS(ADR-0002 i):点击选项,据 ``data-correct`` 标记当场标对错。
# 课程保持静态、可移植(脱离后端仍可打开)。判分读的 ``data-correct`` 与 #006 L9
# 校验读的是同一个标记(一处定义,多处复用)。判分反馈文案是 chrome,随 Workspace
# Language 由常量表注入(#020),两条反馈串以 JSON 编码进 JS(转义安全、可移植)。
def _quiz_js(chrome: dict[str, str]) -> str:
    correct = _json.dumps(chrome["quiz_correct"], ensure_ascii=False)
    wrong = _json.dumps(chrome["quiz_wrong"], ensure_ascii=False)
    return (
        "document.querySelectorAll('[data-quiz]').forEach(function (quiz) {\n"
        "  var feedback = quiz.querySelector('.quiz-feedback');\n"
        "  quiz.querySelectorAll('[data-quiz-option]').forEach(function (option) {\n"
        "    option.addEventListener('click', function () {\n"
        "      var correct = option.getAttribute('data-correct') !== null;\n"
        "      option.classList.add(correct ? 'is-correct' : 'is-wrong');\n"
        "      if (feedback) {\n"
        f"        feedback.textContent = correct ? {correct} : {wrong};\n"
        "      }\n"
        "    });\n"
        "  });\n"
        "});\n"
    )


def _esc(text: str) -> str:
    """HTML 文本转义(保证渲染出的课程可解析、无注入)。"""
    return _html_lib.escape(text or "", quote=True)


def render_lesson_html(draft: LessonDraft, *, lang: str = language.DEFAULT_LANGUAGE) -> str:
    """把结构化 ``LessonDraft`` 确定性渲染成 self-contained 课程 HTML。

    产出的 HTML 满足 #006 的确定性契约:链接共享样式表(可达)、引用作 ``<a>`` 外链
    (URL 来自 RESOURCES.md,L6)、一手资源带 ``primary-source`` marker(L7)、测验
    用 ``data-quiz`` / ``data-quiz-option`` / ``data-correct`` 标记(L9 + 课内 JS 判分)、
    追问提醒带 ``ask-agent`` marker(L13)、跨课锚点指向本地 ``.html``(L12)。
    样式与判分逻辑链接/内置,使课程脱离后端仍可打开。

    ``lang`` 是 Workspace Language 码(#020 / ADR-0013):设定 ``<html lang>``,并选定
    结构性 chrome 文案(「示例讲解」「参考资料」「← 返回全部课程」等)从常量表取——
    不翻译、无额外模型调用;未预置语言回退英文 chrome,课程正文仍是模型按语言产出的内容。
    """
    chrome = language.chrome(lang)
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append(f'<html lang="{_esc(lang)}">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>{_esc(draft.title)}</title>")
    # 链接共享设计系统(每节课都链接它 → 视觉一致;§Assets / L10)。课程在 lessons/,
    # 样式表在 assets/,故相对路径回退一级。
    parts.append(f'<link rel="stylesheet" href="../{SHARED_STYLESHEET}">')
    parts.append("</head>")
    # 技能型课在 <body> 上带 marker(#017):确定性校验据此要求含 worked example 或动手任务。
    skill_attr = " data-skill-lesson" if draft.is_skill_lesson else ""
    parts.append(f"<body{skill_attr}>")
    parts.append(f"<h1>{_esc(draft.title)}</h1>")

    # 正文块(先知识、后练习;L15)。每个引用作上标外链,论断处可点开背书来源(L6)。
    citation_index = {citation.url: i + 1 for i, citation in enumerate(draft.citations)}
    for block in draft.body_blocks:
        if block.kind == "heading":
            parts.append(f"<h2>{_esc(block.text)}</h2>")
        else:
            parts.append(f"<p>{_esc(block.text)}</p>")

    # Worked example(#017 / §D6):knowledge 之后,给代码独立结构位 + 逐步「为什么」注解
    # + takeaway,带 ``data-worked-example`` marker(确定性校验据此判 present)。
    if draft.worked_example is not None:
        parts.extend(_render_worked_example(draft.worked_example, chrome))

    # 动手任务 + 即时自检(#017 / §D6):worked example 之后的紧反馈闭环,带
    # ``data-practice-task`` marker,``expected_result`` 带 ``data-practice-expected`` marker。
    if draft.practice_task is not None:
        parts.extend(_render_practice_task(draft.practice_task, chrome))

    # 一手资源推荐(L7):带约定 marker,#006 据此判 present。标签是 chrome,随语言取。
    parts.append(
        f'<aside class="primary-source" data-primary-source>'
        f'<strong>{_esc(chrome["primary_source_label"])}</strong> '
        f'<a href="{_esc(draft.primary_source.url)}">{_esc(draft.primary_source.label)}</a>'
        f"</aside>"
    )

    # 测验(L8 紧反馈 + L9 无长度泄露 + 课内 JS 即时判分)。正确项带 data-correct。
    parts.append('<section class="quiz" data-quiz>')
    parts.append(f"<p><strong>{_esc(draft.quiz.question)}</strong></p>")
    for option in draft.quiz.options:
        correct_attr = " data-correct" if option.correct else ""
        parts.append(
            f'<button type="button" class="quiz-option" data-quiz-option{correct_attr}>'
            f"{_esc(option.text)}</button>"
        )
    parts.append('<p class="quiz-feedback" aria-live="polite"></p>')
    parts.append("</section>")

    # 引用清单(L6:课程处处带引用 → 列出每条背书外链;URL 必须在 RESOURCES.md)。
    if draft.citations:
        parts.append("<hr>")
        parts.append('<section class="citations">')
        parts.append(f'<h2>{_esc(chrome["references_heading"])}</h2>')
        parts.append("<ol>")
        for citation in draft.citations:
            number = citation_index[citation.url]
            parts.append(
                f'<li id="ref-{number}">{_esc(citation.claim_text)} '
                f'<a href="{_esc(citation.url)}">{_esc(chrome["source_link"])}</a></li>'
            )
        parts.append("</ol>")
        parts.append("</section>")

    # 跨课/参考文档锚点(L12)。课程索引 index.html 由代码维护、保证可达,总是兜底
    # 提供一个本地 .html 锚点;模型给的 cross_links 追加在后——已由 ``_draft`` 用
    # ``validators.local_link_reachable`` 过滤,只余指向磁盘上真实存在文档的可达链接。
    parts.append('<nav class="crosslinks">')
    parts.append(f'<a href="./index.html">{_esc(chrome["all_lessons_nav"])}</a>')
    for link in draft.cross_links:
        parts.append(f' \u00b7 <a href="{_esc(link.href)}">{_esc(link.label)}</a>')
    parts.append("</nav>")

    # 追问提醒(L13):带约定 marker,#006 据此判 present。
    parts.append(
        f'<aside class="ask-agent" data-ask-agent>{_esc(draft.ask_agent_reminder)}</aside>'
    )

    # 课内判分 JS(内置,课程可移植);反馈文案随语言由常量表注入(#020)。
    parts.append(f"<script>{_quiz_js(chrome)}</script>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def _render_worked_example(example: WorkedExample, chrome: dict[str, str]) -> list[str]:
    """把 ``WorkedExample`` 确定性渲染成带 ``data-worked-example`` marker 的代码块区(#017)。

    代码经 ``_esc`` 转义放进 ``<pre><code>``(可移植、无注入);逐步注解作有序列表,
    takeaway 收尾。结构性小标题(「示例讲解」「要点:」)随 Workspace Language 从 chrome
    常量表取(#020)。样式 token 见 ``_SHARED_CSS`` 的 ``.worked-example`` 组。
    """
    parts = ['<section class="worked-example" data-worked-example>']
    parts.append(f'<h2>{_esc(chrome["worked_example_heading"])}</h2>')
    parts.append(
        f'<pre class="code"><code data-lang="{_esc(example.language)}">'
        f"{_esc(example.code)}</code></pre>"
    )
    if example.annotations:
        parts.append('<ol class="annotations">')
        for annotation in example.annotations:
            parts.append(
                f"<li><strong>{_esc(annotation.step_or_line)}</strong>: "
                f"{_esc(annotation.why)}</li>"
            )
        parts.append("</ol>")
    parts.append(
        f'<p class="takeaway"><strong>{_esc(chrome["takeaway_label"])}</strong> '
        f"{_esc(example.takeaway)}</p>"
    )
    parts.append("</section>")
    return parts


def _render_practice_task(task: PracticeTask, chrome: dict[str, str]) -> list[str]:
    """把 ``PracticeTask`` 确定性渲染成带 ``data-practice-task`` marker 的动手任务区(#017)。

    ``expected_result`` 带 ``data-practice-expected`` marker(确定性校验据此判自检可判);
    ``hint`` 可选,折叠在 ``<details>`` 里,免得直接剧透。结构性小标题(「动手练习」
    「预期结果:」「提示」)随 Workspace Language 从 chrome 常量表取(#020)。
    """
    parts = ['<section class="practice-task" data-practice-task>']
    parts.append(f'<h2>{_esc(chrome["practice_heading"])}</h2>')
    parts.append(f"<p>{_esc(task.instructions)}</p>")
    parts.append(
        f'<p class="expected" data-practice-expected>'
        f'<strong>{_esc(chrome["expected_result_label"])}</strong> {_esc(task.expected_result)}</p>'
    )
    if task.hint:
        parts.append(
            f'<details class="hint"><summary>{_esc(chrome["hint_summary"])}</summary>'
            f"<p>{_esc(task.hint)}</p></details>"
        )
    parts.append("</section>")
    return parts


def render_index_html(
    lesson_files: list[tuple[str, str]], *, lang: str = language.DEFAULT_LANGUAGE
) -> str:
    """渲染课程索引 ``lessons/index.html``(确定性维护的课程目录)。

    ``lesson_files`` 为 ``[(filename, title), ...]``。索引链接共享样式表保持视觉一致,
    并给每节课一个锚点;它既是真实有用的目录,又保证每节课有一个可达的本地 ``.html``
    锚点(L12 + 链接可达),无需依赖「下一节课尚不存在」的前向链接。``<html lang>`` 与
    标题 / 占位文案随 Workspace Language(#020):``lang`` 设属性,chrome 常量表出文案。
    """
    chrome = language.chrome(lang)
    parts = [
        "<!DOCTYPE html>",
        f'<html lang="{_esc(lang)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{_esc(chrome["lessons_title"])}</title>',
        f'<link rel="stylesheet" href="../{SHARED_STYLESHEET}">',
        "</head>",
        "<body>",
        f'<h1>{_esc(chrome["lessons_title"])}</h1>',
    ]
    if lesson_files:
        parts.append("<ol>")
        for filename, title in lesson_files:
            parts.append(f'<li><a href="./{_esc(filename)}">{_esc(title)}</a></li>')
        parts.append("</ol>")
    else:
        parts.append(f'<p>{_esc(chrome["no_lessons"])}</p>')
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


# =============================================================================
# 子图状态
# =============================================================================
class LessonState(TypedDict, total=False):
    """Lesson 子图的内部状态(无 checkpointer;在父图单轮内 in-memory 流转)。"""

    # 输入(由 lesson_node 据 TeachState + 工作区装配)。
    user_id: str
    topic_slug: str
    scope: dict
    mission: str
    resources_md: str
    glossary_md: str
    asset_names: list[str]
    lesson_relative: str
    number: int            # 本课编号(commit 时写入已授课 manifest,#015)。
    manifest: list         # 已授课 manifest 条目(喂 draft 防重讲,#015)。
    learner_notes: str     # Learner Notes 原文(喂 draft 使创作贴合偏好/背景,#022)。
    lang: str
    # 工作量。
    attempt: int
    feedback: str          # 上一次失败原因,喂回起草步驱动重写。
    draft: dict
    html: str
    det_results: list      # validators.CheckResult 列表(确定性条目)。
    det_passed: bool
    critique: list         # CritiqueItem 列表。
    critique_passed: bool
    # 输出。
    status: str            # "ok" | "deferred"
    reply: str             # 学习者可见回复(随语言:commit 由 chrome 表出、defer 兜底亦然)。


# =============================================================================
# 子图节点
# =============================================================================
def _draft(state: LessonState) -> dict:
    """起草步(强模型):产出结构化 ``LessonDraft`` → 确定性渲染成 HTML。

    重写时把上一次的失败原因(``feedback``)追加进 system,让模型针对性修正
    (承接 ADR-0006:不达标则带着原因重写,而非盲目重抽)。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    system = prompts.lesson_draft_system(
        state["scope"],
        state["mission"],
        state["resources_md"],
        state.get("asset_names", []),
        state.get("glossary_md", ""),
        _list_linkable_docs(directory),
        # 已授课 manifest(#015 / §D5):让起草步看到「已教过什么」,建立在其上并
        # cross-link,而非重讲已覆盖内容。当前课尚未 commit,故不含自身。
        state.get("manifest", []),
        # Workspace Language(#021 / ADR-0013):课程正文随持久化语言产出,不逐节点重猜。
        state.get("lang", language.DEFAULT_LANGUAGE),
        # Learner Notes(#022 / ADR-0012):据偏好调整讲法、示例贴合系统背景、拆解反复卡点。
        state.get("learner_notes", ""),
    )
    feedback = state.get("feedback", "")
    if feedback:
        system += (
            "\n\nThe previous attempt failed the quality gate for these reasons. "
            "Fix them specifically in this revision:\n" + feedback
        )

    draft: LessonDraft = models.get_model("lesson").with_structured_output(
        LessonDraft
    ).invoke([("system", system), ("human", _scope_human(state["scope"]))])

    # 本次起草需要的新组件先写入 assets/(可复用、idempotent),使课程对它们的链接在
    # 随后的确定性校验里可达(#006 的 links_reachable 按磁盘存在性判定)。
    for component in draft.new_components:
        workspace.write_text(directory, f"assets/{component.filename}", component.content)

    # 确定性丢弃指向磁盘上不存在文件的 cross_link(与 check_links_reachable 共用
    # ``validators.local_link_reachable`` 这一处可达性定义,不另写一份以防漂移)。
    # 模型可能幻觉出兄弟课程/参考链接(尤其首课时别的课程尚不存在),而 #006 的
    # links_reachable 按磁盘存在性判定,任一不可达即整课失败 → 会耗尽重试而暂缓。
    # 渲染器已注入保证可达的 ``./index.html`` 锚点满足 L12,故此处安全丢弃不可达项:
    # 保留 True(存在)与 None(``../reference/x.html`` 之外的外链等非本地文件引用),
    # 只丢 False(本地文件但不存在)。
    base_dir = (directory / state["lesson_relative"]).resolve().parent
    draft.cross_links = [
        link
        for link in draft.cross_links
        if validators.local_link_reachable(link.href, base_dir) is not False
    ]

    html = render_lesson_html(draft, lang=state.get("lang", language.DEFAULT_LANGUAGE))
    return {"draft": draft.model_dump(), "html": html}


def _validate(state: LessonState) -> dict:
    """机器校验步(#006 确定性纯函数,不调 LLM):任一确定性条目失败即整课失败。

    课程文件本身尚未落盘,但其引用的目标(共享样式表、课程索引、本次写入的新组件)
    都已在磁盘,故 ``links_reachable`` 能据 ``lesson_relative`` 正确解析本地链接。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    lesson_path = directory / state["lesson_relative"]
    results = validators.validate_lesson(
        state["html"],
        lesson_path=lesson_path,
        resources_md=state.get("resources_md", ""),
        glossary_md=state.get("glossary_md", ""),
    )
    return {"det_results": results, "det_passed": validators.all_passed(results)}


def _critique(state: LessonState) -> dict:
    """自审步(LLM 对照权威 RUBRIC.md 的判断条目打分)。确定性条目不在此打分。

    达标阈值逐字承接 RUBRIC「Pass threshold」:每个判断条目 ≥ ``CRITIQUE_MIN_ITEM``,
    且均值 ≥ ``CRITIQUE_MIN_MEAN``。
    """
    critique: LessonCritique = models.get_model("lesson").with_structured_output(
        LessonCritique
    ).invoke(
        [
            ("system", prompts.lesson_critique_system()),
            ("human", _critique_human(state["html"])),
        ]
    )
    items = critique.items
    scores = [item.score for item in items]
    # 通过/不通过判定与 LLM-as-judge(#012)共用同一处定义(scoring.passes_threshold):
    # 每个判断条目 ≥ CRITIQUE_MIN_ITEM 且均值 ≥ CRITIQUE_MIN_MEAN。一处定义,三处复用。
    passed = scoring.passes_threshold(scores)
    return {
        "critique": [item.model_dump() for item in items],
        "critique_passed": passed,
    }


def _commit(state: LessonState) -> dict:
    """落盘:写课程 HTML + 重建课程索引。仅在确定性 + 自审双双达标时进入。"""
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    relative = state["lesson_relative"]
    workspace.write_text(directory, relative, state["html"])
    _rebuild_index(directory, state.get("lang", language.DEFAULT_LANGUAGE))
    # 已授课 manifest(#015 / §D5):与课程索引同一时机确定性登记本课(title/objective/
    # summary),作为「已教过什么」的内容级台账,同喂后续 ZPD/draft 防重复。defer 不进此处
    # (只有 commit 才登记),故暂缓的课不入 manifest。
    scope = state["scope"]
    workspace.append_lesson_manifest(
        directory,
        state["number"],
        scope.get("title", ""),
        scope.get("objective", ""),
        _lesson_summary(state.get("draft") or {}),
    )
    # commit 回复随 Workspace Language(#021):chrome 常量表出骨架,课程标题嵌入其中。
    chrome = language.chrome(state.get("lang", language.DEFAULT_LANGUAGE))
    reply = chrome["lesson_commit_reply"].format(title=scope.get("title", ""))
    return {"status": "ok", "reply": reply}


def _revise_or_defer(state: LessonState) -> dict:
    """决定下一步:重试上限内 → 带失败原因重写;耗尽 → 暂缓(不交付未达标版)。"""
    attempt = state.get("attempt", 1)
    if attempt >= config.LESSON_MAX_ATTEMPTS:
        # 重试耗尽:失败姿态(ADR-0009)——不交付,只回「请稍后再来」;不写课程 HTML。
        # 父图照常走到 finalize,checkpointer 完成存档,学习者可无损续接。
        return {"status": "deferred", "reply": _defer_reply(state.get("lang", language.DEFAULT_LANGUAGE))}
    return {"attempt": attempt + 1, "feedback": _feedback_from(state)}


# =============================================================================
# 子图出边(确定性路由)
# =============================================================================
def _after_validate(state: LessonState) -> Literal["critique", "decide"]:
    """确定性条目全过才进自审;否则直接进决策(重写/暂缓)——不浪费一次自审调用。"""
    return "critique" if state.get("det_passed") else "decide"


def _after_critique(state: LessonState) -> Literal["commit", "decide"]:
    """自审达标 → 落盘;否则进决策。"""
    return "commit" if state.get("critique_passed") else "decide"


def _after_decide(state: LessonState) -> Literal["draft", "__end__"]:
    """决策后:仍可重试 → 回起草重写;已暂缓 → 结束。"""
    return END if state.get("status") == "deferred" else "draft"


# =============================================================================
# 装配子图(无 checkpointer:在父图单轮内 in-memory invoke)
# =============================================================================
def build_lesson_subgraph():
    """编译 Lesson 创作子图:draft → validate →(critique)→ commit / 重写 / 暂缓。"""
    builder = StateGraph(LessonState)
    builder.add_node("draft", _draft)
    builder.add_node("validate", _validate)
    builder.add_node("critique", _critique)
    builder.add_node("commit", _commit)
    builder.add_node("decide", _revise_or_defer)

    builder.add_edge(START, "draft")
    builder.add_edge("draft", "validate")
    builder.add_conditional_edges(
        "validate", _after_validate, {"critique": "critique", "decide": "decide"}
    )
    builder.add_conditional_edges(
        "critique", _after_critique, {"commit": "commit", "decide": "decide"}
    )
    builder.add_edge("commit", END)
    builder.add_conditional_edges("decide", _after_decide, {"draft": "draft", END: END})
    return builder.compile()


_SUBGRAPH = build_lesson_subgraph()


# =============================================================================
# 父图节点入口
# =============================================================================
def lesson_node(state: TeachState) -> dict:
    """Lesson 创作能力节点:消费 ZPD 的 ``next_lesson_scope``,跑创作子图产出一节课。

    在 invoke 子图前确定性地铺好工作区的代码拥有产物——共享样式表(每个工作区的第一个
    组件)与课程索引(保证可达的本地 .html 锚点)——使首节课的链接校验即可通过。
    """
    directory = workspace_dir(state["user_id"], state["topic_slug"])
    workspace.ensure_workspace(directory)
    # Workspace Language(#020 / ADR-0013):load_workspace 透出、或 Mission establish 在同
    # 一轮内写回状态;缺失(全新工作区 / 遗留无语言事实)回退默认语言。渲染器据它设
    # ``<html lang>`` 与 chrome 文案,故课程脚手架(索引)也须按同一语言建。
    lang = state.get("workspace_language") or language.DEFAULT_LANGUAGE
    _ensure_shared_assets(directory, lang)

    scope = state.get("next_lesson_scope") or {}
    number = workspace.next_lesson_number(directory)
    slug = topic_slug(scope.get("title", "")) or "lesson"
    lesson_relative = f"lessons/{number:04d}-{slug}.html"

    init: LessonState = {
        "user_id": state["user_id"],
        "topic_slug": state["topic_slug"],
        "scope": scope,
        "mission": workspace.read_text(directory, "MISSION.md") or "",
        "resources_md": workspace.read_text(directory, "RESOURCES.md") or "",
        "glossary_md": workspace.read_text(directory, "GLOSSARY.md") or "",
        "asset_names": _list_assets(directory),
        "lesson_relative": lesson_relative,
        "number": number,
        # 已授课 manifest 读入一次(#015):供起草步防重讲;仅含此前已 committed 的课。
        "manifest": workspace.read_lesson_manifest(directory),
        # Learner Notes 读入一次(#022 / ADR-0012):供起草步据偏好/背景/卡点创作,不再失忆。
        "learner_notes": workspace.read_learner_notes(directory) or "",
        "lang": lang,
        "attempt": 1,
    }
    result = _SUBGRAPH.invoke(init)
    # 交给同一轮内的 Reference 节点(#009):课程已交付才有可压缩之物;暂缓则置 committed=False,
    # Reference 节点据此空操作不产参考文档(承接 ADR-0009 失败姿态)。
    committed = result.get("status") == "ok"
    last_lesson = {
        "committed": committed,
        "scope": scope,
        "summary": _lesson_summary(result.get("draft") or {}) if committed else "",
        "lang": init["lang"],
    }
    return {
        "messages": [AIMessage(result.get("reply") or _defer_reply(lang))],
        "last_lesson": last_lesson,
    }


# =============================================================================
# 确定性工作区辅助
# =============================================================================
def _ensure_shared_assets(directory, lang: str = language.DEFAULT_LANGUAGE) -> None:
    """确保共享样式表与课程索引存在(代码拥有的产物,确定性写入)。初建的空索引按
    Workspace Language 渲染(#020),使 ``<html lang>`` 与目录文案从一开始就随语言。"""
    if not workspace.exists(directory, SHARED_STYLESHEET):
        workspace.write_text(directory, SHARED_STYLESHEET, _SHARED_CSS)
    if not workspace.exists(directory, LESSONS_INDEX):
        workspace.write_text(directory, LESSONS_INDEX, render_index_html([], lang=lang))


def _rebuild_index(directory, lang: str = language.DEFAULT_LANGUAGE) -> None:
    """扫描 ``lessons/`` 重建索引,纳入所有已落盘的课程(按文件名升序);按 Workspace
    Language 渲染 ``<html lang>`` 与目录文案(#020)。"""
    files = workspace.scan_files(directory)
    lessons: list[tuple[str, str]] = []
    for relative in sorted(files):
        if relative.startswith("lessons/") and relative.endswith(".html"):
            filename = relative.split("/", 1)[1]
            if filename == "index.html":
                continue
            lessons.append((filename, _title_from_html(directory, relative)))
    workspace.write_text(directory, LESSONS_INDEX, render_index_html(lessons, lang=lang))


def _list_assets(directory) -> list[str]:
    """列出 ``assets/`` 下的组件文件名(供起草步「先读 assets 再拼」)。"""
    assets_dir = directory / "assets"
    if not assets_dir.exists():
        return []
    return sorted(p.name for p in assets_dir.iterdir() if p.is_file())


def _list_linkable_docs(directory) -> list[str]:
    """列出可被 cross_link 指向的**已存在**文档(其他课程 + 参考文档),以相对课程所在
    ``lessons/`` 目录的 href 表示,交给起草步——模型只能链已存在的文档,不再幻觉。

    - 课程 ``lessons/0001-x.html`` → ``./0001-x.html``;课程索引 ``index.html`` 不列入
      (渲染器已自动注入其锚点,它是 L12 的兜底,不需要模型再链)。
    - 参考文档 ``reference/y.html`` → ``../reference/y.html``。
    """
    hrefs: list[str] = []
    for relative in sorted(workspace.scan_files(directory)):
        if not relative.endswith(".html"):
            continue
        if relative.startswith("lessons/"):
            filename = relative.split("/", 1)[1]
            if filename != "index.html":
                hrefs.append(f"./{filename}")
        elif relative.startswith("reference/"):
            hrefs.append(f"../{relative}")
    return hrefs


def _title_from_html(directory, relative: str) -> str:
    """从课程 HTML 抽 <title>(索引展示用);抽不到则回退文件名。"""
    content = workspace.read_text(directory, relative) or ""
    start = content.find("<title>")
    end = content.find("</title>")
    if start != -1 and end != -1 and end > start:
        return content[start + len("<title>"):end].strip()
    return relative.rsplit("/", 1)[-1]


# =============================================================================
# 小工具
# =============================================================================
def _scope_human(scope: dict) -> str:
    """给起草步的 human 消息:复述要教的范围。"""
    return f"Draft the lesson for: {scope.get('title', '')} — {scope.get('objective', '')}"


def _critique_human(html: str) -> str:
    """给自审步的 human 消息:把待评的课程 HTML 交给评分模型。"""
    return "Here is the lesson to score (HTML):\n\n" + html


def _lesson_summary(draft: dict) -> str:
    """把已交付课程的结构化内容浓成一段文本,供 Reference 节点压缩成参考文档。

    取标题 + 正文块文本(剥去 HTML 渲染细节);Reference 节点据此产出课程的耐用对应物。
    """
    parts = [draft.get("title", "")]
    for block in draft.get("body_blocks", []):
        text = block.get("text", "") if isinstance(block, dict) else ""
        if text:
            parts.append(text)
    return "\n".join(part for part in parts if part)


def _feedback_from(state: LessonState) -> str:
    """把本次失败(确定性条目 + 自审低分项)汇成下一次重写的针对性反馈。"""
    lines: list[str] = []
    for result in state.get("det_results", []):
        if not result.passed:
            lines.append(f"- [deterministic] {result.name}: {result.detail}")
    for item in state.get("critique", []):
        if item.get("score", 5) < config.CRITIQUE_MIN_ITEM:
            lines.append(
                f"- [rubric {item.get('id')}] scored {item.get('score')}: "
                f"{item.get('justification', '')}"
            )
    return "\n".join(lines) or "- The lesson did not meet the quality threshold."


__all__ = [
    "lesson_node",
    "build_lesson_subgraph",
    "render_lesson_html",
    "render_index_html",
    "LessonDraft",
    "LessonCritique",
    "Citation",
    "PrimarySource",
    "Quiz",
    "QuizOption",
    "Block",
    "CrossLink",
    "NewComponent",
    "WorkedExample",
    "ExampleAnnotation",
    "PracticeTask",
    "CritiqueItem",
    "LessonState",
    "SHARED_STYLESHEET",
    "LESSONS_INDEX",
]
