"""RUBRIC 评分缝(#012):LLM-as-judge + 人评校准。

这是 RUBRIC.md「一处定义,三处复用」的第二、三处(第一处是 Lesson 子图的课内自审,
ADR-0006 / #007):

- **LLM-as-judge**:对**固定课程样本**,按 RUBRIC.md 的**判断条目**(L1–L17 中标
  ``*(Judgement)*`` 的项)打分 1–5,用与课内自审完全相同的阈值判定(每项 ≥
  ``CRITIQUE_MIN_ITEM`` 且均值 ≥ ``CRITIQUE_MIN_MEAN``)。确定性条目不在此打分——
  它们由 #006 机器校验强制,不经 judge。
- **人评校准**:先用人评(权威)校准 LLM-judge,使其成为可自动化的代理指标。逐项打分
  要足够贴近人评、且通过/不通过判定要足够一致(见 ``Calibration.calibrated``)。
- **回归监控**:judge over 同一组样本可重复运行,跟踪课程教学质量随时间/改动的变化。

**与课内自审同源(关键纪律)**:judge 复用 ``prompts.lesson_critique_system()``——同一份
嵌入 RUBRIC.md 原文的 system prompt,同一个 ``lesson.LessonCritique`` 结构化 schema,
同一组阈值。评分依据绝不在此另抄一份,避免「三处复用」漂成三套标准。

判断条目集合**从 RUBRIC.md 解析**(标记为 ``*(Judgement)*`` 的项),而非在代码里硬抄,
让 RUBRIC.md 始终是「哪些条目该判断」的单一事实源。

本模块的纯函数(阈值、校准指标、判断条目解析)可脱离模型/磁盘直测;judge 调用经
``models.get_model("judge")``,测试用 conftest 的 ``models_director`` 注入确定性打分。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config, models, prompts

# RUBRIC.md Part 1 里「判断条目」的识别:形如 ``**L4 — ...** *(Judgement)*`` 或
# ``**L11 — ...** *(Judgement — may require viewing a screenshot)*``。
# 关键:只匹配括注以 ``Judgement`` 起头的项;L17 的括注以 ``Deterministic`` 起头
# (「Deterministic where programmatically comparable; otherwise Judgement」),据
# 「source coverage note」归确定性校验(#006 的 L17),故被排除,不在 judge 打分面内。
_JUDGEMENT_ITEM_RE = re.compile(r"\*\*(L\d+)\b[^\n]*?\*\(Judgement[^)]*\)\*")


@lru_cache(maxsize=1)
def judgement_item_ids() -> tuple[str, ...]:
    """从权威 RUBRIC.md 解析出**判断**条目的 id(按文档顺序,去重)。

    单一事实源:judge 该给哪些条目打分,由 RUBRIC.md 的 ``*(Judgement)*`` 标记决定,
    不在代码里硬抄一份。确定性条目(L6/L7/L9/L12/L13 与归确定性的 L17)不在其中——
    它们由 #006 机器校验把关。
    """
    path = Path(config.RUBRIC_PATH)
    if not path.exists():
        raise RuntimeError(
            f"找不到 RUBRIC.md(配置 RUBRIC_PATH={config.RUBRIC_PATH!r})。"
            f"LLM-as-judge 需要权威评分依据,请确认仓库根存在 RUBRIC.md。"
        )
    rubric_md = path.read_text(encoding="utf-8")
    # 去重保序:dict.fromkeys 按首次出现顺序保留唯一 id。
    return tuple(dict.fromkeys(_JUDGEMENT_ITEM_RE.findall(rubric_md)))


# =============================================================================
# 阈值(与课内自审同源:一处定义,Lesson 子图与 judge 共用)
# =============================================================================
def mean_score(scores: Iterable[int]) -> float:
    """判断条目打分的均值;空集回 0.0(永不除零)。"""
    values = list(scores)
    return sum(values) / len(values) if values else 0.0


def passes_threshold(scores: Iterable[int]) -> bool:
    """RUBRIC「Pass threshold」逐字承接:每个判断条目 ≥ ``CRITIQUE_MIN_ITEM`` 且
    判断项均值 ≥ ``CRITIQUE_MIN_MEAN``。

    Lesson 子图自审(``lesson._critique``)与 LLM-as-judge 共用本函数——通过/不通过的
    判定只此一处定义,三处复用不会漂。空集视为不通过(没打到分不能算过)。
    """
    values = list(scores)
    return (
        bool(values)
        and all(score >= config.CRITIQUE_MIN_ITEM for score in values)
        and mean_score(values) >= config.CRITIQUE_MIN_MEAN
    )


# =============================================================================
# 数据模型:judge 打分 / 人评标注 / 校准结果
# =============================================================================
@dataclass(frozen=True)
class JudgeResult:
    """LLM-as-judge 对一个课程样本的逐判断条目打分。"""

    sample_id: str
    scores: dict[str, int]  # 判断条目 id -> 1–5(只含判断条目)。

    @property
    def mean(self) -> float:
        return mean_score(self.scores.values())

    @property
    def passed(self) -> bool:
        return passes_threshold(self.scores.values())


@dataclass(frozen=True)
class HumanAnnotation:
    """人评(权威)对一个课程样本的逐判断条目打分(校准基准)。"""

    sample_id: str
    scores: dict[str, int]  # 判断条目 id -> 1–5。

    @property
    def passed(self) -> bool:
        return passes_threshold(self.scores.values())


@dataclass(frozen=True)
class Sample:
    """一个固定课程样本:HTML + 其人评标注。"""

    id: str
    html: str
    human: HumanAnnotation


@dataclass(frozen=True)
class Calibration:
    """LLM-judge 对齐人评的校准结果(可自动化代理指标的可信度)。"""

    samples: int           # 参与比对的样本数。
    item_pairs: int        # 逐项(judge,human)比对对数。
    exact_agreement: float # 逐项完全一致占比。
    within_one: float      # 逐项 |judge-human| ≤ 1 占比(主校准指标)。
    mean_abs_error: float  # 逐项绝对误差均值。
    decision_agreement: float  # 通过/不通过判定一致的样本占比。

    @property
    def calibrated(self) -> bool:
        """达标线([ours]):逐项足够贴近(within_one)且判定足够一致(decision)。

        达标才可把 LLM-judge 当作可自动化的代理指标用于回归监控;否则需调 prompt / 换档。
        """
        return (
            self.within_one >= config.JUDGE_CALIBRATION_WITHIN_ONE
            and self.decision_agreement >= config.JUDGE_CALIBRATION_DECISION_AGREEMENT
        )


# =============================================================================
# LLM-as-judge(复用课内自审的同一份 RUBRIC prompt + schema)
# =============================================================================
def _judge_human(html: str) -> str:
    """给 judge 的 human 消息:把待评课程 HTML 交给评分模型(与课内自审同构)。

    刻意与 ``lesson._critique_human`` 保持同一措辞(同源):judge 与课内自审看到的待评
    输入框架一致。两处不在同一模块(为打破 lesson↔scoring 的导入环),改一处时同改另一处。
    """
    return "Here is the lesson to score (HTML):\n\n" + html


def judge_lesson(sample_id: str, html: str, *, node: str = "judge") -> JudgeResult:
    """对一节课程 HTML 跑 LLM-as-judge,按 RUBRIC.md 判断条目打分。

    评分依据 = ``prompts.lesson_critique_system()``(嵌入 RUBRIC.md 原文,与课内自审
    同源);schema = ``lesson.LessonCritique``。模型即便误给确定性条目打了分,也按
    ``judgement_item_ids()`` 过滤掉——judge 只对判断条目负责,确定性条目交 #006。
    """
    from . import lesson  # 局部导入避免与 lesson(顶层 import scoring)成环。

    critique = (
        models.get_model(node)
        .with_structured_output(lesson.LessonCritique)
        .invoke(
            [
                ("system", prompts.lesson_critique_system()),
                ("human", _judge_human(html)),
            ]
        )
    )
    judged = set(judgement_item_ids())
    scores = {item.id: item.score for item in critique.items if item.id in judged}
    return JudgeResult(sample_id=sample_id, scores=scores)


def run_judge(samples: list[Sample], *, node: str = "judge") -> list[JudgeResult]:
    """对一组固定样本逐个跑 judge(回归监控的取数步)。"""
    return [judge_lesson(sample.id, sample.html, node=node) for sample in samples]


# =============================================================================
# 人评校准(纯函数:逐项 + 判定两层一致性)
# =============================================================================
def calibrate(
    judge_results: list[JudgeResult], human: list[HumanAnnotation]
) -> Calibration:
    """把 LLM-judge 打分与人评(权威)对齐,产出校准指标。

    - **逐项一致性**:对每个样本中 judge 与人评**都打了分**的判断条目,比对分差,
      汇成 exact / within_one / mean_abs_error。
    - **判定一致性**:对每个匹配样本,比对 judge 与人评在同一阈值下的通过/不通过判定。

    judge 与人评按 ``sample_id`` 匹配;只有人评里也存在的样本参与比对(人评是基准)。
    """
    human_by_id = {annotation.sample_id: annotation for annotation in human}
    diffs: list[int] = []
    decision_hits = 0
    matched = 0
    for result in judge_results:
        annotation = human_by_id.get(result.sample_id)
        if annotation is None:
            continue
        matched += 1
        for item_id, judge_score in result.scores.items():
            if item_id in annotation.scores:
                diffs.append(judge_score - annotation.scores[item_id])
        if result.passed == annotation.passed:
            decision_hits += 1

    pairs = len(diffs)
    exact = sum(1 for d in diffs if d == 0) / pairs if pairs else 0.0
    within_one = sum(1 for d in diffs if abs(d) <= 1) / pairs if pairs else 0.0
    mae = sum(abs(d) for d in diffs) / pairs if pairs else 0.0
    decision = decision_hits / matched if matched else 0.0
    return Calibration(
        samples=matched,
        item_pairs=pairs,
        exact_agreement=exact,
        within_one=within_one,
        mean_abs_error=mae,
        decision_agreement=decision,
    )


# =============================================================================
# 样本集 IO + 端到端校准跑批
# =============================================================================
def load_samples(directory: str | Path | None = None) -> list[Sample]:
    """从样本目录加载固定课程样本 + 人评标注。

    目录布局:``manifest.json``(``{"samples": [{id, html, human_scores}, ...]}``)
    + 各样本 HTML 文件。人评 ``human_scores`` 只覆盖判断条目(确定性条目不在此评)。
    """
    base = Path(directory or config.JUDGE_SAMPLES_DIR)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            f"找不到评分样本清单(期望 {manifest_path})。"
            f"回归监控需要固定课程样本 + 人评标注。"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_resolved = base.resolve()
    samples: list[Sample] = []
    for index, entry in enumerate(manifest.get("samples", [])):
        try:
            sample_id = entry["id"]
            html_rel = entry["html"]
            human_scores = entry["human_scores"]
        except KeyError as exc:
            raise RuntimeError(
                f"{manifest_path} 第 {index} 个样本缺字段 {exc.args[0]!r}"
                f"(需要 id / html / human_scores)。"
            ) from exc
        # 边界校验:样本 HTML 路径不得逃出样本目录(directory 可由调用方传入)。
        html_path = (base / html_rel).resolve()
        if not html_path.is_relative_to(base_resolved):
            raise ValueError(f"样本 HTML 路径越界,拒绝读取:{html_rel!r}")
        html = html_path.read_text(encoding="utf-8")
        scores = {str(k): int(v) for k, v in human_scores.items()}
        samples.append(
            Sample(
                id=sample_id,
                html=html,
                human=HumanAnnotation(sample_id=sample_id, scores=scores),
            )
        )
    return samples


def run_calibration(directory: str | Path | None = None) -> Calibration:
    """端到端回归监控:加载固定样本 → 跑 LLM-judge → 与人评校准 → 返回指标。

    可重复运行(judge 节点 ``temperature`` 由模型层决定);指标用于持续监控课程教学
    质量是否随改动漂移,以及 LLM-judge 是否仍贴合人评而可继续当代理指标用。
    """
    samples = load_samples(directory)
    judge_results = run_judge(samples)
    return calibrate(judge_results, [sample.human for sample in samples])


__all__ = [
    "judgement_item_ids",
    "mean_score",
    "passes_threshold",
    "JudgeResult",
    "HumanAnnotation",
    "Sample",
    "Calibration",
    "judge_lesson",
    "run_judge",
    "calibrate",
    "load_samples",
    "run_calibration",
]
