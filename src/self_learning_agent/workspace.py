"""学习者工作区的文件读写(ADR-0003:文件是 B/C 层的单一事实源)。

每个 ``(user_id, topic)`` 拥有一个隔离目录 ``workspaces/{user_id}/{topic_slug}/``,
里面放长期学习者记忆(B:``MISSION.md`` / ``learning-records/`` / ``GLOSSARY.md`` /
``RESOURCES.md``)与学习产物(C:``lessons/*`` / ``reference/*`` / ``assets/*``)。

本模块只提供**确定性**的文件原语,不含任何教学逻辑:

- ``workspace_dir`` / ``ensure_workspace``:定位与建目录(命名空间隔离)。
- ``scan_files`` + ``diff_new``:用「会话开始的基线快照」与「会话结束的当前快照」
  作差,算出**本轮新产出/改动的产物**——回复里要附带的产物引用就来自这里。
  把「本轮产物」做成对文件系统的派生量,意味着任何能力节点只要写文件即可被
  自动识别,无需各自记得登记(契合「文件是单一事实源」)。

根目录在调用时从 ``config.WORKSPACES_ROOT`` 读取,便于测试 monkeypatch 到临时目录。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config
from .sanitize import sanitize_surrogates
from .tenancy import topic_slug

# learning-records 文件名前缀:四位序号 + 连字符(承接 LEARNING-RECORD-FORMAT.md
# 的 ``0001-slug.md`` 约定)。用于扫描已有序号、推导下一条记录的编号。
_RECORD_PREFIX = re.compile(r"^(\d{4})-")
_LEARNING_RECORDS_DIR = "learning-records"
# lessons 文件名前缀:同 learning-records 的 ``NNNN-slug`` 约定(SKILL.md §Lessons:49
# 「titled 0001-<dash-case-name>.html where the number increments each time」)。
_LESSONS_DIR = "lessons"
# reference 文件名前缀:同 lessons 的 ``NNNN-slug.html`` 约定。参考文档是课程的耐用
# 对应物(SKILL.md §Reference Documents:122–136),与课程同构地编号 / 落盘 / 维护索引。
_REFERENCE_DIR = "reference"

# Workspace Language 事实文件(#020 / ADR-0013):工作区级小 JSON 元文件,在 Mission
# 确立时据学习者输入检测一次、持久化,下游节点与渲染器读它而非逐节点重猜(单一事实源,
# 承接 ADR-0003)。它是**内部工作区事实**而非学习者可见产物,故从 ``diff_new`` 的本轮
# 产物账里剔除(``_INTERNAL_META_FILES``)——调用方要渲染给终端用户的是课程/参考等产物,
# 不是这份语言配置。
_WORKSPACE_META_FILE = "workspace.json"

# 内部工作区元文件(非学习者产物):``diff_new`` 计算「本轮新产物」时跳过它们,免得把
# 语言配置这类内部事实当成产物引用回流给调用方。``scan_files`` 仍如实扫到它们(诚实的
# 底层快照原语);只有「算产物」这一步据此过滤。
_INTERNAL_META_FILES = frozenset({_WORKSPACE_META_FILE})

# 已授课 manifest 文件(#015 / 设计 §D5):记「已教过什么」的内容级台账,防止后续章节
# 重复。与 ``lessons/index.html`` 同处 lessons/,在每次课程 commit 时确定性维护;每条
# ``{number, title, objective, summary, committed_at}``。它是「已教过」的单一事实源
# (承接 ADR-0003 文件即事实源),跨会话可靠,同喂 ZPD(不重选已覆盖 scope)与 draft
# (建立在其上、cross-link 而非重讲)。defer 的课不 commit,故不入 manifest。
# ``committed_at``(#024 / ADR-0012)是 commit 时刻的 ISO-8601 UTC 时间戳:显式、可审计地
# 记录「何时教的」,供 ``derive_spacing_review`` 据它 + 当前时间派生「该复习什么」间隔复习
# 信号。选它而非从课程文件 mtime 派生——时间信息与 Coverage Ledger 同处单一事实源、
# 不受文件复制/重写扰动;旧 manifest 无此字段时派生逻辑优雅退化(见 ``derive_spacing_review``)。
_LESSON_MANIFEST_FILE = "lessons/manifest.json"

# 词汇表文件名(承接 GLOSSARY-FORMAT.md:工作区根的 ``GLOSSARY.md``)。
_GLOSSARY_FILE = "GLOSSARY.md"
# 一个词条头的形状:``**Term**:``(GLOSSARY-FORMAT.md 的 Structure 示例)。
_GLOSSARY_TERM_HEADER = re.compile(r"^\*\*(.+?)\*\*:\s*$")
# 禁用别名行:``_Avoid_: a, b``(GLOSSARY-FORMAT.md 示例)。与 validators 的 L17 校验
# 读同一信号——一处定义,多处复用:upsert 写出它 → 课程创作读它 → L17 验证它。
_GLOSSARY_AVOID_LINE = re.compile(r"_Avoid_:\s*(.+)", re.IGNORECASE)
# 词汇表里的固定小标题(本确定性渲染器只产扁平 ``## Terms`` 列表;GLOSSARY-FORMAT.md
# 「A flat list is fine when terms cohere」允许扁平形)。解析 header 时剔除它,渲染时重加。
_GLOSSARY_TERMS_HEADING = re.compile(r"^##\s+Terms\s*$", re.IGNORECASE)


def workspace_dir(user_id: str, topic_slug: str) -> Path:
    """返回某 ``(user_id, topic_slug)`` 的工作区目录路径(不保证已存在)。"""
    return Path(config.WORKSPACES_ROOT) / user_id / topic_slug


def ensure_workspace(directory: Path) -> Path:
    """确保工作区目录存在(含父目录),返回该路径。"""
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def scan_files(directory: Path) -> dict[str, float]:
    """递归扫描目录下所有文件 → ``{相对路径: mtime}`` 快照。

    目录不存在时返回空快照(尚未产出任何产物的全新学习者)。
    """
    if not directory.exists():
        return {}
    snapshot: dict[str, float] = {}
    for path in directory.rglob("*"):
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            snapshot[relative] = path.stat().st_mtime
    return snapshot


def diff_new(baseline: dict[str, float], current: dict[str, float]) -> list[str]:
    """对比基线与当前快照,返回**新增或被改动**的相对路径(已排序)。

    新增文件(基线里没有)是本轮产物的主要情形;mtime 变大覆盖「同名改写」。
    内部工作区元文件(``_INTERNAL_META_FILES``,如 Workspace Language 配置)不是学习者
    可见产物,故不计入本轮产物账——调用方要展示给终端用户的是课程/参考等产物。
    """
    changed = [
        relative
        for relative, mtime in current.items()
        if relative not in _INTERNAL_META_FILES
        and (relative not in baseline or mtime > baseline[relative])
    ]
    return sorted(changed)


def read_workspace_language(directory: Path) -> str | None:
    """读工作区持久化的 Workspace Language 码(#020 / ADR-0013);未持久化返回 ``None``。

    容错:文件缺失 / 空 / 损坏 / 无 ``language`` 字段一律返回 ``None``,让读侧(load_workspace
    与各渲染器)据此回退默认语言,无需各自 try/except。纯确定性读入,便于单测。
    """
    content = read_text(directory, _WORKSPACE_META_FILE)
    if not content or not content.strip():
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    language = data.get("language")
    return language if isinstance(language, str) and language.strip() else None


def write_workspace_language(directory: Path, language: str) -> Path:
    """把 Workspace Language 码持久化为工作区事实(#020 / ADR-0013),返回写入路径。

    确定性原语(无教学判断,与 ``append_lesson_manifest`` 同构):**写不写 / 写什么码**是
    Mission establish 的判断(据学习者输入检测一次),**怎么写**(JSON 落盘到单一元文件)
    收敛在这里。幂等覆盖:同一工作区语言一经确立即稳定,重复写同码不产生差异。
    """
    return write_text(
        directory,
        _WORKSPACE_META_FILE,
        json.dumps({"language": language}, ensure_ascii=False, indent=2) + "\n",
    )


def write_text(directory: Path, relative_path: str, content: str) -> Path:
    """在工作区内写一个文本产物(自动建父目录),返回写入的绝对路径。

    落盘前在此系统边界清洗孤立代理项(见 ``sanitize.py``):上游模型偶发吐出的孤立
    UTF-8 代理项若直接 strict UTF-8 落盘会抛 ``UnicodeEncodeError``,这里统一替换成
    U+FFFD,让**所有**产物写入(课程/参考/MISSION/RESOURCES/记录/GLOSSARY)都走同一
    道护栏。
    """
    target = directory / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sanitize_surrogates(content), encoding="utf-8")
    return target


def read_text(directory: Path, relative_path: str) -> str | None:
    """读工作区内某文本产物;不存在返回 ``None``。"""
    target = directory / relative_path
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")


def exists(directory: Path, relative_path: str) -> bool:
    """工作区内某产物是否存在。"""
    return (directory / relative_path).exists()


def read_learning_records(directory: Path) -> list[str]:
    """读 ``learning-records/`` 下所有记录正文,按序号升序返回(无记录时为空)。

    ZPD 节点据学习记录推算最近发展区(LEARNING-RECORD-FORMAT.md:「They are used
    to calculate the zone of proximal development」)。纯确定性扫描+排序,便于单测;
    只取带 ``NNNN-`` 前缀的记录文件,按序号排,使「最近学到的在最后」语义稳定。
    """
    records_dir = directory / _LEARNING_RECORDS_DIR
    if not records_dir.exists():
        return []
    numbered: list[tuple[int, str]] = []
    for path in sorted(records_dir.iterdir()):
        if not path.is_file():
            continue
        match = _RECORD_PREFIX.match(path.name)
        if match:
            numbered.append((int(match.group(1)), path.read_text(encoding="utf-8")))
    return [body for _, body in sorted(numbered, key=lambda item: item[0])]


def next_record_number(directory: Path) -> int:
    """扫描 ``learning-records/`` 取最高序号 + 1(无记录时为 1)。

    承接 LEARNING-RECORD-FORMAT.md「Scan for the highest existing number and
    increment by one」。纯确定性扫描,便于单测;目录 lazily 创建(写入时才建)。
    """
    return _next_number(directory / _LEARNING_RECORDS_DIR)


def append_learning_record(
    directory: Path,
    title: str,
    body: str,
    *,
    evidence: str | None = None,
    implications: str | None = None,
) -> Path:
    """按 LEARNING-RECORD-FORMAT.md 的命名/格式约定追加一条学习记录,返回写入路径。

    确定性原语(无教学判断):序号自增(``next_record_number``)、标题归一成 slug、
    正文按 Template 的最小格式(``# title`` + 一段正文)落盘。**写不写**是各能力
    节点的教学判断(P6 证据纪律由 Assessment 节点把关),但**怎么写**收敛在这里
    的纯文件原语,便于单测、避免各节点重复编号/命名逻辑(承接 LEARNING-RECORD-
    FORMAT.md「Scan for the highest existing number and increment by one」+ Template)。

    ``evidence`` / ``implications`` 是 LEARNING-RECORD-FORMAT.md「Optional sections」
    (#023 / ADR-0012):仅当有内容才落成 ``## Evidence`` / ``## Implications`` 小节
    (「Only include these when they add genuine value」)。为空则退化为最小 Template,
    与改前逐字节一致(不给可选段的记录不受影响)。``Status`` 不在此写——新记录默认
    ``active``(隐含),``superseded`` 由 ``supersede_learning_record`` 事后标注。
    """
    number = next_record_number(directory)
    slug = topic_slug(title) or "learning-record"
    relative = f"{_LEARNING_RECORDS_DIR}/{number:04d}-{slug}.md"
    return write_text(
        directory, relative, _render_learning_record(title, body, evidence, implications)
    )


def _render_learning_record(
    title: str, body: str, evidence: str | None, implications: str | None
) -> str:
    """把学习记录渲染成 Template(可选段仅在有内容时追加),末尾单个换行。"""
    parts = [f"# {title}", "", body.rstrip()]
    if evidence and evidence.strip():
        parts += ["", "## Evidence", "", evidence.strip()]
    if implications and implications.strip():
        parts += ["", "## Implications", "", implications.strip()]
    return "\n".join(parts) + "\n"


def supersede_learning_record(
    directory: Path, number: int, superseded_by: int
) -> Path | None:
    """把编号 ``number`` 的旧记录标为 ``Status: superseded by LR-NNNN``,返回写入路径。

    确定性原语(无教学判断,与 ``append_learning_record`` 同构):**标不标**是 Assessment
    节点的教学判断(后写记录纠正/深化了旧理解时),**怎么写**(据编号定位文件、写/更新
    Status frontmatter、正文原样保留)收敛在这里。承接 LEARNING-RECORD-FORMAT.md
    「Supersession」——**不删除**旧记录(理解演化史本身是信号),只加一行状态,使过时
    假设不再误导 ZPD 选课。旧记录不存在时返回 ``None``(闸门在节点侧;此处仅诚实落盘)。
    幂等:重复标注只更新 Status 值,正文不变。
    """
    path = _find_record_path(directory, number)
    if path is None:
        return None
    updated = _set_record_status(
        path.read_text(encoding="utf-8"), f"superseded by LR-{superseded_by:04d}"
    )
    return write_text(directory, f"{_LEARNING_RECORDS_DIR}/{path.name}", updated)


def learning_record_exists(directory: Path, number: int) -> bool:
    """某编号的学习记录文件是否存在(supersession 闸门用,避免指向幻觉编号)。"""
    return _find_record_path(directory, number) is not None


def _find_record_path(directory: Path, number: int) -> Path | None:
    """据四位编号前缀定位 ``learning-records/`` 下的记录文件;无则 ``None``。"""
    records_dir = directory / _LEARNING_RECORDS_DIR
    if not records_dir.exists():
        return None
    prefix = f"{number:04d}-"
    for path in sorted(records_dir.iterdir()):
        if path.is_file() and path.name.startswith(prefix):
            return path
    return None


def _split_record_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """把可选的 YAML-ish frontmatter 与正文分开;无 frontmatter 时返回 ``({}, content)``。

    只需兼容本模块渲染器写出的极简 ``key: value`` frontmatter(记录默认无 frontmatter,
    仅 supersession 会加),故不引第三方 YAML 解析。
    """
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            block, body = content[4:end], content[end + len("\n---\n") :]
            fm: dict[str, str] = {}
            for line in block.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    fm[key.strip()] = value.strip()
            return fm, body
    return {}, content


def _set_record_status(content: str, status: str) -> str:
    """在记录文本上写/更新 ``Status`` frontmatter,正文原样保留。"""
    frontmatter, body = _split_record_frontmatter(content)
    frontmatter["Status"] = status
    lines = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    return f"---\n{lines}\n---\n{body}"


def next_lesson_number(directory: Path) -> int:
    """扫描 ``lessons/`` 取最高序号 + 1(无课时为 1)。

    承接 SKILL.md §Lessons:49「titled 0001-<dash-case-name>.html where the number
    increments each time」。与 ``next_record_number`` 同构的纯确定性扫描,供 Lesson
    创作子图(#007)给新课命名;只数带 ``NNNN-`` 前缀的 ``.html``(忽略 index 等)。
    """
    return _next_number(directory / _LESSONS_DIR, suffix=".html")


def read_lesson_manifest(directory: Path) -> list[dict]:
    """读已授课 manifest ``lessons/manifest.json`` → 条目列表(按 ``number`` 升序)。

    不存在 / 空 / 损坏时返回空列表(全新学习者或尚无 committed 课),使读侧无需各自
    容错。每条 ``{number, title, objective, summary}``。同 ``read_learning_records``
    的纯确定性读入:ZPD(#005)与 Lesson 起草(#007)据此看到「已教过什么」。
    """
    content = read_text(directory, _LESSON_MANIFEST_FILE)
    if not content or not content.strip():
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    entries = [entry for entry in data if isinstance(entry, dict)]
    return sorted(entries, key=lambda entry: entry.get("number", 0))


def append_lesson_manifest(
    directory: Path,
    number: int,
    title: str,
    objective: str,
    summary: str,
    *,
    committed_at: str | None = None,
) -> Path:
    """在课程 commit 时确定性 upsert 一条 manifest 条目,返回写入路径。

    确定性原语(无教学判断,与 ``append_learning_record`` 同构):**写不写**是 Lesson
    子图的判断(仅 committed 的课才登记,defer 不登记),**怎么写**(编号去重 upsert、
    升序、JSON 落盘)收敛在这里。按 ``number`` upsert(同号覆盖),使重复 commit 幂等
    不产生重复条目。

    ``committed_at``(#024 / ADR-0012)记「何时教的」ISO-8601 UTC 时间戳,供间隔复习派生。
    默认取当前 UTC 时间(commit 时刻即授课时刻);测试可显式注入以保持 hermetic/确定性。
    重新 commit 同号课会刷新此戳(重教即重置该课的复习计时),与内容级 upsert 语义一致。
    """
    stamp = committed_at or datetime.now(timezone.utc).isoformat()
    entries = [
        entry for entry in read_lesson_manifest(directory) if entry.get("number") != number
    ]
    entries.append(
        {
            "number": number,
            "title": title,
            "objective": objective,
            "summary": summary,
            "committed_at": stamp,
        }
    )
    entries.sort(key=lambda entry: entry.get("number", 0))
    return write_text(
        directory,
        _LESSON_MANIFEST_FILE,
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
    )


def _parse_manifest_timestamp(value: object) -> datetime | None:
    """把 manifest 条目的 ``committed_at`` 解析成 tz-aware ``datetime``;无法解析返回 ``None``。

    容错优雅退化(#024 验收:旧 manifest 无时间信息时不报错):非字符串 / 空 / 非 ISO 格式
    一律返回 ``None`` → 该条目不参与间隔复习派生。无 tzinfo 的裸时间戳按 UTC 解读(与写侧
    ``append_lesson_manifest`` 的 UTC 落盘一致)。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def derive_spacing_review(
    manifest: list[dict],
    *,
    now: datetime | None = None,
    review_after_days: float | None = None,
) -> list[dict]:
    """据 Coverage Ledger(manifest 的 ``committed_at``)+ 当前时间派生「该复习什么」信号。

    间隔复习(spacing / ADR-0012)的确定性落地:teach 原靠宿主 ambient memory 判断「该复习
    什么」,移植版据 Coverage Ledger 的授课时间戳 + 当前时间显式派生。一节课 committed 超过
    ``review_after_days``(默认 ``config.SPACING_REVIEW_DAYS``)即到期,列入复习候选;按授课
    时间升序返回(最久未复习的在前),每条 ``{number, title, objective, days_since}``。

    此信号喂入 ZPD(选课)使 spacing 从隐性判断变为显式机制;retrieval(课内 quiz)与
    interleave(draft prompt)不受影响。**优雅退化**:``committed_at`` 缺失/损坏的条目被
    跳过(不报错),故旧 manifest(#015 之前、无时间戳)派生出空信号而非崩溃。纯确定性,
    ``now`` 可注入以 hermetic 单测。
    """
    threshold = timedelta(
        days=config.SPACING_REVIEW_DAYS if review_after_days is None else review_after_days
    )
    current = now or datetime.now(timezone.utc)
    due: list[tuple[datetime, dict]] = []
    for entry in manifest:
        stamp = _parse_manifest_timestamp(entry.get("committed_at"))
        if stamp is None:
            continue  # 无时间信息 → 无法计算间隔 → 优雅跳过(承接旧 manifest 退化)
        age = current - stamp
        if age >= threshold:
            due.append(
                (
                    stamp,
                    {
                        "number": entry.get("number"),
                        "title": entry.get("title", ""),
                        "objective": entry.get("objective", ""),
                        "days_since": age.days,
                    },
                )
            )
    due.sort(key=lambda item: item[0])  # 最久未复习的在前(授课时间升序)
    return [payload for _, payload in due]


def next_reference_number(directory: Path) -> int:
    """扫描 ``reference/`` 取最高序号 + 1(无参考文档时为 1)。

    承接 SKILL.md §Reference Documents:参考文档是课程的耐用对应物,与课程**同构地**
    编号 / 落盘。与 ``next_lesson_number`` 同构的纯确定性扫描,供 Reference 节点(#009)
    给新参考文档命名;只数带 ``NNNN-`` 前缀的 ``.html``(忽略 index 等非编号产物)。
    """
    return _next_number(directory / _REFERENCE_DIR, suffix=".html")


def _next_number(subdir: Path, *, suffix: str | None = None) -> int:
    """扫描某子目录里带 ``NNNN-`` 前缀的文件,返回最高序号 + 1(无则 1)。

    ``suffix`` 非空时只数该后缀的文件(lessons 用 ``.html`` 排除 index.html 等
    非编号产物);learning-records 不限后缀。
    """
    if not subdir.exists():
        return 1
    highest = 0
    for path in subdir.iterdir():
        if not path.is_file():
            continue
        if suffix is not None and path.suffix.lower() != suffix:
            continue
        match = _RECORD_PREFIX.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


# === GLOSSARY.md 维护(P7 的确定性「怎么写」原语)===============================
# 与 ``append_learning_record`` 同构:**写不写**是 Assessment 节点的教学判断(P7 证据
# 纪律——仅当学习者真正理解某术语才促入),**怎么写**(格式 / 去重 / upsert)收敛在这里
# 的纯文件原语,便于单测、避免节点重复格式化逻辑。产出的 ``_Avoid_:`` 别名同时驱动
# validators 的 L17 校验(入表术语在后续课程被一致使用)。
def upsert_glossary_term(
    directory: Path,
    term: str,
    definition: str,
    aliases: list[str] | None = None,
    *,
    topic: str = "",
) -> Path:
    """按 GLOSSARY-FORMAT.md 的格式 upsert 一个词条,返回写入路径。

    确定性原语(无教学判断):若 ``GLOSSARY.md`` 不存在则建骨架;若同名词条已存在则
    **就地修订**(承接 GLOSSARY-FORMAT.md「Update in place; do not leave stale entries」),
    否则追加。术语匹配大小写不敏感。文件始终由本渲染器写出,保持单一规范扁平形,故
    解析无需兼容任意手写 Markdown(B 层文件的单一事实源即本原语)。
    """
    term = (term or "").strip()
    definition = (definition or "").strip()
    cleaned_aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
    header, terms = _parse_glossary(read_text(directory, _GLOSSARY_FILE), topic)

    updated: list[tuple[str, str, list[str]]] = []
    replaced = False
    for existing_term, existing_def, existing_aliases in terms:
        if existing_term.lower() == term.lower():
            updated.append((term, definition, cleaned_aliases))
            replaced = True
        else:
            updated.append((existing_term, existing_def, existing_aliases))
    if not replaced:
        updated.append((term, definition, cleaned_aliases))

    return write_text(directory, _GLOSSARY_FILE, _render_glossary(header, updated))


def _parse_glossary(
    content: str | None, topic: str
) -> tuple[str, list[tuple[str, str, list[str]]]]:
    """把 GLOSSARY.md 解析成 ``(header, [(term, definition, aliases), ...])``。

    header 是首个词条之前的内容(标题 + 可选描述),剔除固定的 ``## Terms`` 小标题
    (渲染时重加)。每个词条由 ``**Term**:`` 头起,后续非别名行折叠为定义、``_Avoid_:``
    行解析为别名。内容为空时按 ``topic`` 造最小骨架标题。
    """
    if not content or not content.strip():
        return (f"# {topic} Glossary".strip() if topic else "# Glossary"), []

    header_lines: list[str] = []
    terms: list[tuple[str, str, list[str]]] = []
    current_term: str | None = None
    current_def: list[str] = []
    current_aliases: list[str] = []

    def _flush() -> None:
        nonlocal current_term, current_def, current_aliases
        if current_term is not None:
            terms.append((current_term, " ".join(current_def).strip(), current_aliases))
        current_term, current_def, current_aliases = None, [], []

    for line in content.splitlines():
        head = _GLOSSARY_TERM_HEADER.match(line.strip())
        if head:
            _flush()
            current_term = head.group(1).strip()
        elif current_term is not None:
            avoid = _GLOSSARY_AVOID_LINE.search(line)
            if avoid:
                current_aliases.extend(
                    a.strip() for a in avoid.group(1).split(",") if a.strip()
                )
            elif line.strip():
                current_def.append(line.strip())
        elif not _GLOSSARY_TERMS_HEADING.match(line.strip()):
            header_lines.append(line)
    _flush()

    header = "\n".join(header_lines).strip()
    if not header:
        header = f"# {topic} Glossary".strip() if topic else "# Glossary"
    return header, terms


def _render_glossary(header: str, terms: list[tuple[str, str, list[str]]]) -> str:
    """把 header + 词条列表渲染回 GLOSSARY-FORMAT.md 的规范扁平形。"""
    parts = [header.rstrip(), "", "## Terms", ""]
    for term, definition, aliases in terms:
        parts.append(f"**{term}**:")
        parts.append(definition)
        if aliases:
            parts.append(f"_Avoid_: {', '.join(aliases)}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# === RESOURCES.md 维护(P2 / RESOURCES-FORMAT 的确定性渲染 + 解析 + 社区 upsert)====
# 与 GLOSSARY.md 同构:RESOURCES.md 的**格式**(Knowledge/Wisdom 分组、逐条标注、
# opt-out note、Gaps)由这里的确定性渲染器**单一产出**。Research 节点(#004)curate
# 整份资源后调 ``write_resources``;Wisdom 节点(#010)只对 ``## Wisdom (Communities)``
# 段做增量 ``upsert_communities``。两个节点写同一份文件却共用同一对渲染器/解析器,避免
# 两套渲染逻辑漂移(ADR-0003:文件是 B 层单一事实源)。因 RESOURCES.md 始终由本渲染器
# 写出,解析器只需兼容本渲染器的输出,无需兼容任意手写 Markdown(同 GLOSSARY 的假设)。
_RESOURCES_FILE = "RESOURCES.md"
# 一条带链接的资源/社区行:``- [label](url)``(RESOURCES-FORMAT.md 的 Structure 示例)。
_RES_LINK_LINE = re.compile(r"^- \[(.+?)\]\((.+?)\)\s*$")
# 一条无链接的纯文本行(线下社区 ``- Local: ...`` / opt-out note / 占位符)。
_RES_BULLET_LINE = re.compile(r"^- (.+?)\s*$")
# opt-out note 的识别标记(渲染器写出 "the learner has opted out ...";大小写不敏感)。
_RES_OPT_OUT_MARK = "opted out"


@dataclass(frozen=True)
class KnowledgeSource:
    """一条知识资源(RESOURCES.md ``## Knowledge`` 段的一行 + 标注)。"""

    title: str
    url: str
    annotation: str = ""


@dataclass(frozen=True)
class Community:
    """一条社区资源(``## Wisdom (Communities)`` 段)。``url`` 可空(线下社区)。"""

    name: str
    url: str | None = None
    annotation: str = ""


@dataclass
class ResourcesDoc:
    """RESOURCES.md 的结构化全量视图(供确定性渲染 / 解析 / 增量 upsert)。"""

    topic: str = ""
    knowledge: list[KnowledgeSource] = field(default_factory=list)
    communities: list[Community] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    community_opt_out: bool = False


def render_resources(doc: ResourcesDoc) -> str:
    """把 ``ResourcesDoc`` 渲染成 RESOURCES.md(严格按 RESOURCES-FORMAT 的分组/标注/空白)。

    渲染规则忠实承接 RESOURCES-FORMAT.md:按 Knowledge / Wisdom 分组、逐条标注、
    社区偏好(opt-out)显式记录、Gaps 显式列出。两组各自为空时给出占位提示(让文件
    始终自解释)。**这是 RESOURCES.md 的唯一渲染器**——Research 与 Wisdom 节点都经此落盘。
    """
    lines: list[str] = [f"# {doc.topic} Resources", "", "## Knowledge", ""]
    for source in doc.knowledge:
        lines.append(f"- [{source.title}]({source.url})")
        if source.annotation:
            lines.append(f"  {source.annotation}")
    if not doc.knowledge:
        lines.append("- (No trusted knowledge sources curated yet.)")

    lines += ["", "## Wisdom (Communities)", ""]
    for community in doc.communities:
        if community.url:
            lines.append(f"- [{community.name}]({community.url})")
        else:
            lines.append(f"- {community.name}")
        if community.annotation:
            lines.append(f"  {community.annotation}")
    if doc.community_opt_out:
        # RESOURCES-FORMAT「Record community preferences」:记下学习者已选择不加入社区,
        # 免得未来会话反复推荐(P2 / P4 respect opt-out)。
        lines.append("- Note: the learner has opted out of joining communities.")
    elif not doc.communities:
        lines.append("- (No trusted communities curated yet.)")

    if doc.gaps:
        # RESOURCES-FORMAT「Surface gaps explicitly」:列出使命需要但暂无好资源的领域。
        lines += ["", "## Gaps", ""]
        for gap in doc.gaps:
            lines.append(f"- {gap}")

    return "\n".join(lines) + "\n"


def parse_resources(content: str | None, topic: str = "") -> ResourcesDoc:
    """把 RESOURCES.md 文本解析回 ``ResourcesDoc``(只需兼容本模块渲染器的输出)。

    解析规则与 ``render_resources`` 互逆:首个 ``# … Resources`` 取主题;``## Knowledge``
    / ``## Wisdom (Communities)`` / ``## Gaps`` 切段;带链接行解析成资源/社区,无链接纯文本
    行按段语义解析(Wisdom 段里命中 opt-out 标记 → 置偏好位,占位符 ``- (No …)`` 跳过,
    其余作线下社区);缩进续行折叠为上一条目的标注。
    """
    doc = ResourcesDoc(topic=topic)
    if not content or not content.strip():
        return doc

    section: str | None = None
    knowledge: list[list] = []      # [title, url, annotation]
    communities: list[list] = []    # [name, url|None, annotation]
    gaps: list[str] = []
    opt_out = False
    last: list | None = None  # 指向当前可追加标注的条目(knowledge/community 的可变行)

    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith("# ") and stripped.endswith("Resources"):
            parsed_topic = stripped[2:].removesuffix("Resources").strip()
            if parsed_topic:
                doc.topic = parsed_topic
            section, last = None, None
            continue
        if stripped.startswith("## "):
            head = stripped[3:].strip().lower()
            section = (
                "knowledge" if head.startswith("knowledge")
                else "wisdom" if head.startswith("wisdom")
                else "gaps" if head.startswith("gaps")
                else None
            )
            last = None
            continue
        if not stripped:
            continue

        # 缩进续行(非 bullet)→ 折叠为上一条目的标注(渲染器用两空格缩进标注)。
        if raw[:1] in (" ", "\t") and not stripped.startswith("- ") and last is not None:
            last[2] = (f"{last[2]} {stripped}").strip()
            continue

        link = _RES_LINK_LINE.match(stripped)
        bullet = _RES_BULLET_LINE.match(stripped)
        if section == "knowledge" and link:
            entry = [link.group(1), link.group(2), ""]
            knowledge.append(entry)
            last = entry
        elif section == "wisdom":
            if _RES_OPT_OUT_MARK in stripped.lower():
                opt_out, last = True, None
            elif link:
                entry = [link.group(1), link.group(2), ""]
                communities.append(entry)
                last = entry
            elif bullet and not bullet.group(1).startswith("("):
                entry = [bullet.group(1), None, ""]
                communities.append(entry)
                last = entry
        elif section == "gaps" and bullet:
            gaps.append(bullet.group(1))
            last = None

    doc.knowledge = [KnowledgeSource(t, u, a) for t, u, a in knowledge]
    doc.communities = [Community(n, u, a) for n, u, a in communities]
    doc.gaps = gaps
    doc.community_opt_out = opt_out
    return doc


def read_resources(directory: Path, topic: str = "") -> ResourcesDoc | None:
    """读 + 解析工作区的 RESOURCES.md;不存在返回 ``None``(尚无 curate 的全新学习者)。"""
    content = read_text(directory, _RESOURCES_FILE)
    if content is None:
        return None
    return parse_resources(content, topic)


def write_resources(directory: Path, doc: ResourcesDoc) -> Path:
    """把整份 ``ResourcesDoc`` 渲染并落盘 RESOURCES.md(Research 节点 curate 后用)。"""
    return write_text(directory, _RESOURCES_FILE, render_resources(doc))


# === NOTES.md 维护(Learner Notes,三层记忆之第三层)===========================
# 承接 ADR-0012:Learner Notes 是 teach 宿主 ambient 对话记忆的**显式替身**——记录学习者
# 的偏好 / 节奏 / 反复卡点 / 未解决疑问 / 系统背景。它从 teach 的"可选 scratchpad"升级为
# 移植版的**承重记忆层**;缺它,生成节点(zpd/lesson/mission)失忆、课程质量退化。与
# ``append_learning_record`` / ``append_lesson_manifest`` 同构:**写不写 / 记什么**是节点的
# 教学判断(捕捉到偏好/卡点/背景/疑问时触发),**怎么写**(合并 / 去重 / 落盘)收敛在这里
# 的纯文件原语。它是学习者可见产物(user story 19),故**不**入 ``_INTERNAL_META_FILES``。
_NOTES_FILE = "NOTES.md"

# Learner Notes 类别(ADR-0012 五类字段)。键(schema / 内部用)→ 渲染标题(学习者可见)。
# dict 顺序即渲染顺序,稳定。``state.CapturedNote`` 的 Literal 必须与这些键一致——
# ``append_learner_notes`` 静默丢弃未知类别作为防漂移的安全网。
_NOTE_CATEGORIES: dict[str, str] = {
    "preference": "Preferences",
    "pace": "Pace",
    "sticking_point": "Sticking points",
    "open_question": "Open questions",
    "background": "Background",
}
# 渲染标题(小写)→ 类别键,供解析既有 NOTES.md 时反查(与 ``_render_learner_notes`` 互逆)。
_NOTE_HEADING_TO_CATEGORY = {heading.lower(): key for key, heading in _NOTE_CATEGORIES.items()}


@dataclass(frozen=True)
class LearnerNote:
    """一条 Learner Note:``category`` 是 ``_NOTE_CATEGORIES`` 的键,``text`` 是内容。

    这是**确定性原语的输入类型**(节点把模型产出的捕捉项翻译成它再落盘),与 LLM 侧的
    ``state.CapturedNote`` 结构对应但分层:pydantic schema 管"模型怎么报",本 dataclass
    管"怎么写文件"。
    """

    category: str
    text: str


def read_learner_notes(directory: Path) -> str | None:
    """读工作区 ``NOTES.md`` 原文(供 zpd/lesson/mission 的 prompt 注入);不存在返回 ``None``。

    与 ``read_text`` 同构的纯读入:生成节点把它作为三层记忆之一(连同 Coverage Ledger 与
    Learning Records)带进 system prompt,取代宿主的 ambient 记忆(ADR-0012)。
    """
    return read_text(directory, _NOTES_FILE)


def _parse_learner_notes(content: str | None) -> dict[str, list[str]]:
    """把 ``NOTES.md`` 文本解析回 ``{category_key: [text, ...]}``(只需兼容本模块渲染器输出)。

    与 ``_render_learner_notes`` 互逆:``## <Heading>`` 切段(标题反查类别键),段内 ``- `` bullet
    收为该类别的条目。始终返回全类别键(空列表占位),使 upsert 无需各自容错。
    """
    notes: dict[str, list[str]] = {key: [] for key in _NOTE_CATEGORIES}
    if not content or not content.strip():
        return notes
    current: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = _NOTE_HEADING_TO_CATEGORY.get(stripped[3:].strip().lower())
        elif current and stripped.startswith("- "):
            entry = stripped[2:].strip()
            if entry:
                notes[current].append(entry)
    return notes


def _render_learner_notes(notes: dict[str, list[str]]) -> str:
    """把 ``{category_key: [text, ...]}`` 渲染成 ``NOTES.md`` 的规范形(只渲染非空类别)。"""
    parts: list[str] = ["# Learner Notes", ""]
    for key, heading in _NOTE_CATEGORIES.items():
        entries = notes.get(key) or []
        if not entries:
            continue
        parts.append(f"## {heading}")
        parts.append("")
        parts.extend(f"- {entry}" for entry in entries)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def append_learner_notes(directory: Path, notes: list[LearnerNote]) -> Path | None:
    """把若干 Learner Note **合并 / 去重 / 落盘**进 ``NOTES.md``,返回写入路径(无可写项返回 ``None``)。

    确定性原语(无教学判断,与 ``append_learning_record`` 同构):**写不写 / 记什么**是节点的
    教学判断,**怎么写**(读入既有、按类别大小写不敏感去重后追加、按 ``_NOTE_CATEGORIES``
    顺序渲染)收敛在这里。滚动更新:既有条目保留、新条目追加,重复(同类别同文本)不产生
    差异——使反复写同一偏好幂等。未知类别 / 空文本被丢弃(防 schema 漂移的安全网)。
    """
    cleaned = [
        (note.category, note.text.strip())
        for note in notes
        if note.category in _NOTE_CATEGORIES and note.text and note.text.strip()
    ]
    if not cleaned:
        return None
    existing = _parse_learner_notes(read_text(directory, _NOTES_FILE))
    for category, text in cleaned:
        seen = {entry.casefold() for entry in existing[category]}
        if text.casefold() not in seen:
            existing[category].append(text)
    return write_text(directory, _NOTES_FILE, _render_learner_notes(existing))


def upsert_communities(
    directory: Path,
    communities: list[Community],
    *,
    opt_out: bool,
    topic: str = "",
) -> Path:
    """把社区 / opt-out 偏好**增量** upsert 进 RESOURCES.md 的 Wisdom 段,返回写入路径。

    确定性原语(无教学判断,Wisdom 节点 #010 / P4 调用):RESOURCES.md 不存在则建最小骨架
    (只有 Wisdom 段),存在则读入、保留 Knowledge / Gaps 段不动,只往 Wisdom 段**追加**新
    社区(按 ``(name, url)`` 大小写不敏感去重,非破坏性,不动既有条目)。``community_opt_out``
    一旦为真即**sticky**(``existing or opt_out``)——忠实承接 §Acquiring Wisdom「If the user
    expresses a preference that they don't want to join a community, respect it」:偏好一旦表达
    便持久尊重,后续会话不再反复推荐。**写不写 / 记什么社区**是 Wisdom 节点的教学判断,
    **怎么写**(格式 / 去重 / sticky)收敛在这里的纯文件原语,便于单测、避免节点重复渲染逻辑。
    """
    doc = read_resources(directory, topic) or ResourcesDoc(topic=topic)
    if topic and not doc.topic:
        doc.topic = topic
    seen = {(c.name.lower(), c.url) for c in doc.communities}
    for community in communities:
        key = (community.name.lower(), community.url)
        if key not in seen:
            doc.communities.append(community)
            seen.add(key)
    doc.community_opt_out = doc.community_opt_out or opt_out
    return write_resources(directory, doc)
