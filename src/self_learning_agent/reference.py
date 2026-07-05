"""Reference 节点(P5 / #009):把刚写好的课程压缩成可快速查阅的参考文档。

承接 SKILL.md §Reference Documents(逐字切片在 ``prompts._REFERENCE_DOCUMENTS``):

    While creating lessons, you should also create reference documents.
    ... They should be the compressed essence of the lesson, in a format
    designed for quick reference.

教学法纪律:参考文档是课程的**耐用对应物**——课程鲜少回看,参考文档会;故参考文档剥去
课程的散文、例子、脚手架,只留可一眼扫到的压缩单元(速查表 / 算法 / 语法卡 / 例程 /
词汇表)。它与课程**同构地**编号 / 落盘 / 维护索引(承接 workspace 的 ``next_reference_
number`` 与本模块的 ``reference/index.html``)。

控制流:本节点紧跟 Lesson 节点(图边 ``lesson → reference → finalize``),消费
``state["last_lesson"]``:

- 课程**已交付**(``committed``)→ 强档 LLM 产结构化 ``ReferenceDoc``,确定性渲染成
  与课程视觉一致的 HTML 参考卡(链接同一张共享样式表),落盘 + 重建参考索引。
- 课程**暂缓**(重试耗尽未达标,ADR-0009 失败姿态)→ **无可压缩之物**,本节点空操作
  直接放行(不产参考文档)。

与 Lesson 子图同构的脚手架契约:模型只产结构化字段(标题、形态、摘要、压缩条目),HTML
渲染 / 落盘 / 索引由确定性代码接管(承接「质量由架构保证」)。参考文档不走 Lesson 的质量
门子图——它是课程的派生压缩物,不含测验 / 引用等需机器校验的元素;但它**遵循 GLOSSARY**
术语(``reference_system`` 把 GLOSSARY.md 喂入,禁用 ``_Avoid_:`` 别名),与 L17 一致性
原则同源。本节点不产学习者可见消息——参考文档是课程产出的**副产物**,经 finalize 的产物
diff 作为「本轮新产物」回流给调用方(承接「文件是单一事实源,本轮产物是其派生量」)。
"""

from __future__ import annotations

import html as _html_lib

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import language, models, prompts, workspace
from .lesson import SHARED_STYLESHEET
from .state import TeachState
from .tenancy import topic_slug
from .workspace import workspace_dir

# 参考索引的固定相对路径(代码拥有,确定性维护——同 lessons/index.html)。
REFERENCE_INDEX = "reference/index.html"


# =============================================================================
# 结构化输出 schema(模型只产这些;HTML 渲染 / 文件写入由确定性代码接管)
# =============================================================================
class ReferenceItem(BaseModel):
    """一条压缩的知识单元:标签 + 紧凑细节(为扫读而非阅读设计)。"""

    label: str = Field(description="Short label / key for quick scanning.")
    detail: str = Field(description="Terse detail — what a practitioner needs at a glance.")


class ReferenceDoc(BaseModel):
    """Reference 节点的结构化产物(渲染器据此拼出 HTML 参考卡)。"""

    title: str = Field(description="Short dash-case-friendly name (the thing it lets you look up).")
    kind: str = Field(
        description="The reference form: cheatsheet, algorithm, syntax, routine, or glossary."
    )
    summary: str = Field(description="One line — what this reference covers and when to reach for it.")
    items: list[ReferenceItem] = Field(
        default_factory=list, description="The compressed units of knowledge worth keeping."
    )


# =============================================================================
# 确定性渲染(共享设计系统)——纯函数,不调 LLM
# =============================================================================
def _esc(text: str) -> str:
    """HTML 文本转义(保证渲染出的参考文档可解析、无注入)。"""
    return _html_lib.escape(text or "", quote=True)


def render_reference_html(doc: ReferenceDoc, *, lang: str = language.DEFAULT_LANGUAGE) -> str:
    """把结构化 ``ReferenceDoc`` 确定性渲染成 self-contained 参考卡 HTML。

    链接与课程**同一张**共享样式表(``../assets/lesson.css``,因 reference/ 与 lessons/
    同深),使参考文档与课程视觉一致(§Assets / L10 的「看起来像一门连贯的课程」)。
    用定义列表(``<dl>``)承载压缩条目——为快速查阅而设计的紧凑形态。

    ``lang`` 是 Workspace Language 码(#020/#021 / ADR-0013):设 ``<html lang>``,并选定
    结构性 chrome(「← 返回全部参考」「课程」)从常量表取——不翻译;未预置语言回退英文 chrome,
    条目内容仍是模型按语言产出的内容。
    """
    chrome = language.chrome(lang)
    parts: list[str] = [
        "<!DOCTYPE html>",
        f'<html lang="{_esc(lang)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(doc.title)}</title>",
        f'<link rel="stylesheet" href="../{SHARED_STYLESHEET}">',
        "</head>",
        "<body>",
        f"<h1>{_esc(doc.title)}</h1>",
        f'<p class="subtitle">{_esc(doc.kind)} \u00b7 {_esc(doc.summary)}</p>',
    ]
    if doc.items:
        parts.append('<dl class="reference">')
        for item in doc.items:
            parts.append(f"<dt>{_esc(item.label)}</dt>")
            parts.append(f"<dd>{_esc(item.detail)}</dd>")
        parts.append("</dl>")
    # 跨文档锚点:回参考索引 + 课程索引(与课程互链,§Reference Documents:
    # 「Lessons can reference these documents」的反向连结)。文案随语言从 chrome 取。
    parts.append('<nav class="crosslinks">')
    parts.append(f'<a href="./index.html">{_esc(chrome["all_references_nav"])}</a>')
    parts.append(f' \u00b7 <a href="../lessons/index.html">{_esc(chrome["lessons_nav"])}</a>')
    parts.append("</nav>")
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


def render_reference_index_html(
    reference_files: list[tuple[str, str]], *, lang: str = language.DEFAULT_LANGUAGE
) -> str:
    """渲染参考索引 ``reference/index.html``(确定性维护的参考目录)。

    ``reference_files`` 为 ``[(filename, title), ...]``。链接共享样式表保持视觉一致,
    给每份参考一个锚点——既是真实有用的目录,又保证参考文档间可达互链。``<html lang>`` 与
    标题 / 占位文案随 Workspace Language(#021):``lang`` 设属性,chrome 常量表出文案。
    """
    chrome = language.chrome(lang)
    parts = [
        "<!DOCTYPE html>",
        f'<html lang="{_esc(lang)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{_esc(chrome["references_index_title"])}</title>',
        f'<link rel="stylesheet" href="../{SHARED_STYLESHEET}">',
        "</head>",
        "<body>",
        f'<h1>{_esc(chrome["references_index_title"])}</h1>',
    ]
    if reference_files:
        parts.append("<ol>")
        for filename, title in reference_files:
            parts.append(f'<li><a href="./{_esc(filename)}">{_esc(title)}</a></li>')
        parts.append("</ol>")
    else:
        parts.append(f'<p>{_esc(chrome["no_references"])}</p>')
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


# =============================================================================
# 父图节点入口
# =============================================================================
def reference_node(state: TeachState) -> dict:
    """Reference 能力节点:把刚交付的课程压缩成一份参考文档(暂缓的课则空操作)。"""
    last_lesson = state.get("last_lesson") or {}
    if not last_lesson.get("committed"):
        # 课程暂缓(ADR-0009 失败姿态)→ 无可压缩之物,放行不产参考文档。
        return {}

    directory = workspace_dir(state["user_id"], state["topic_slug"])
    mission = workspace.read_text(directory, "MISSION.md") or ""
    glossary_md = workspace.read_text(directory, "GLOSSARY.md") or ""
    scope = last_lesson.get("scope", {})
    lesson_summary = last_lesson.get("summary", "")
    # Workspace Language(#021 / ADR-0013):课程节点透传的持久化语言码,reference 字段随它
    # 产出、渲染器据它设 <html lang> 与 chrome。缺失(遗留 last_lesson)回退默认语言。
    lang = last_lesson.get("lang") or language.DEFAULT_LANGUAGE

    doc: ReferenceDoc = models.get_model("reference").with_structured_output(
        ReferenceDoc
    ).invoke(
        [
            SystemMessage(
                prompts.reference_system(scope, mission, lesson_summary, glossary_md, lang)
            ),
            HumanMessage(_reference_human(scope)),
        ]
    )

    number = workspace.next_reference_number(directory)
    slug = topic_slug(doc.title) or "reference"
    relative = f"reference/{number:04d}-{slug}.html"
    workspace.write_text(directory, relative, render_reference_html(doc, lang=lang))
    _rebuild_reference_index(directory, lang)
    return {}


# =============================================================================
# 确定性工作区辅助
# =============================================================================
def _rebuild_reference_index(directory, lang: str = language.DEFAULT_LANGUAGE) -> None:
    """扫描 ``reference/`` 重建索引,纳入所有已落盘的参考文档(按文件名升序);按 Workspace
    Language 渲染 ``<html lang>`` 与目录文案(#021)。"""
    files = workspace.scan_files(directory)
    references: list[tuple[str, str]] = []
    for relative in sorted(files):
        if relative.startswith("reference/") and relative.endswith(".html"):
            filename = relative.split("/", 1)[1]
            if filename == "index.html":
                continue
            references.append((filename, _title_from_html(directory, relative)))
    workspace.write_text(
        directory, REFERENCE_INDEX, render_reference_index_html(references, lang=lang)
    )


def _title_from_html(directory, relative: str) -> str:
    """从参考 HTML 抽 <title>(索引展示用);抽不到则回退文件名。"""
    content = workspace.read_text(directory, relative) or ""
    start = content.find("<title>")
    end = content.find("</title>")
    if start != -1 and end != -1 and end > start:
        return content[start + len("<title>"):end].strip()
    return relative.rsplit("/", 1)[-1]


def _reference_human(scope: dict) -> str:
    """给 Reference 节点的 human 消息:复述要压缩的课程。"""
    return (
        f"Distil the lesson into a reference document: "
        f"{scope.get('title', '')} — {scope.get('objective', '')}"
    )


__all__ = [
    "reference_node",
    "render_reference_html",
    "render_reference_index_html",
    "ReferenceDoc",
    "ReferenceItem",
    "REFERENCE_INDEX",
]
