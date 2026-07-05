# RUBRIC.md — Lesson & Agent Quality Rubric

> **Status:** authoritative scoring source. This file is **LLM-facing** — it is sent to the model
> (self-critique step of the Lesson authoring sub-graph, ADR-0006) and reused for human review and
> LLM-as-judge scoring. Per the project language rule, **this file is in English**.
>
> **承接说明(中文,非 LLM-facing):** 本文件逐条承接 `teach/SKILL.md` 与四个 FORMAT 文件中的判定标准。
> 标 **[verbatim]** 的条目为原文逐字摘录,**不得改动一个词**。标 **[ours]** 的为我们新增的评分脚手架
> (刻度、阈值、judge 指示),原 skill 中没有,可调整。每条标注来源段落与判定方式。
> 一处定义,三处复用:课内自审(ADR-0006)、人评(权威)、LLM-as-judge(可自动化代理指标)。

---

## How to score [ours]

Each item is one of two kinds:

- **Deterministic** — checkable by code, **not** by an LLM. Pass/fail. These are enforced by the
  Lesson authoring sub-graph's mechanical validation step (ADR-0006), **not** scored here by a judge.
- **Judgement** — requires a human or LLM to read the lesson. Scored **1–5**
  (1 = clearly fails the standard, 3 = partially meets it, 5 = fully exemplifies it).

**Pass threshold [ours]:**
- **All deterministic items MUST pass (100%).** A single deterministic failure fails the lesson.
- **Every judgement item MUST score ≥ 3, AND the mean of all judgement items MUST be ≥ 4.0.**
- A lesson failing the threshold is sent back to the draft step to be revised (ADR-0006), up to the
  maximum retry count; on exhaustion the failure posture applies (ADR-0009): do not deliver a
  sub-threshold lesson.

The same threshold is the authoritative bar for human review and the calibration target for the
LLM-as-judge.

---

## Part 1 — Lesson rubric (L1–L17)

The object scored is a single produced lesson (one self-contained HTML file).

### A. Mission fit

**L1 — Tied to the mission.** *(Judgement)*
Source: SKILL.md §Lessons:53, §The Mission:71–79.
[verbatim] "It should be directly tied to the mission" / "Every lesson should be tied into the mission - the reason that the user is interested in learning about the topic."

**L2 — Stays within the mission.** *(Judgement)*
Source: SKILL.md §The Mission:71–79.
The lesson does not drift into content outside the learner's mission.

### B. Zone of Proximal Development

**L3 — Single tightly-scoped thing.** *(Judgement)*
Source: SKILL.md §Lessons:49.
[verbatim] "A **lesson** is a single, self-contained HTML output that teaches one tightly-scoped thing tied to the mission."

**L4 — "Challenged just enough" / within working memory.** *(Judgement)*
Source: SKILL.md §ZPD:83, §Lessons:53.
[verbatim] "the user should always feel as if they are being challenged 'just enough'." /
[verbatim] "The lesson should be short, and completable very quickly. Learners' working memory is very small, and we need to stay within it."

### C. Knowledge acquisition

**L5 — A single tangible win.** *(Judgement)*
Source: SKILL.md §Lessons:53.
[verbatim] "each lesson should give the user a single tangible win that they can build on."

**L6 — Every claim is cited.** *(Deterministic — count claims vs citations; verify each citation resolves to RESOURCES.md)*
Source: SKILL.md §Knowledge:95.
[verbatim] "Lessons should be littered with citations - links to external resources to back up any claim made."

**L7 — Recommends one highest-quality primary source.** *(Deterministic — present/absent)*
Source: SKILL.md §Lessons:59.
[verbatim] "Each lesson should recommend a primary source for the user to read or watch. This should be the most high-quality, high-trust resource you found on the topic."

**L14 — Only the knowledge required for the skill.** *(Judgement)*
Source: SKILL.md §Knowledge:93.
[verbatim] "The knowledge in the lesson should be only what's required to acquire that skill."

### D. Skills & tight feedback

**L8 — Feedback-loop-based practice (for skills).** *(Judgement)*
Source: SKILL.md §Skills:103–108.
[verbatim] "Skills should be taught through interactive lessons." /
[verbatim] "Each of these should be based on a **feedback loop**, where the user receives feedback on their performance. This feedback loop should be as tight as possible, giving feedback immediately - and ideally automatically."

**L9 — Quiz options give no formatting/length tell.** *(Deterministic — the marked-correct option must not be a length outlier among the distractors)*
Source: SKILL.md §Skills:110.
[verbatim] "For quizzes, each answer should be exactly the same number of words (and characters, if possible). Don't give the user any clues about the answer through formatting."
[ours] Enforcement note (semantics first): the verbatim guidance ("exactly the same number of words") is carried to the lesson-drafting prompt as **authoring guidance**. The deterministic gate, however, enforces only the *purpose* clause — that the correct answer is not betrayed by length — by failing a quiz only when its marked-correct option is a length outlier (significantly longer or shorter than **every** distractor). Forcing exact equality as a hard gate would distort option wording; semantic consistency and expressive power take priority. Subtle equal-length polish is left to the self-critique / human judgement layer.

**L15 — Teach knowledge first, then practice skills.** *(Judgement)*
Source: SKILL.md §Knowledge:93.
[verbatim] "You teach the knowledge first, then get the user to practice the skills via an interactive feedback loop."

### E. Durability — desirable difficulty

**L16 — Uses desirable difficulty (retrieval practice / spacing / interleaving).** *(Judgement)*
Source: SKILL.md §Fluency vs Storage Strength:41–45.
[verbatim] "Try to design lessons which build long-term retention by desirable difficulty:" /
[verbatim] "Using retrieval practice (recall from memory)" /
[verbatim] "Spacing (distributing practice over time)" /
[verbatim] "Interleaving (mixing up different but related topics in practice - for skills practice only)"

### F. Consistency & beauty

**L10 — Reuses shared components; looks like one course.** *(Judgement)*
Source: SKILL.md §Assets:63–69.
[verbatim] "Reuse is the default, not the exception. Before authoring a lesson, read `./assets/` and build from the components already there." /
[verbatim] "every lesson links it, so the lessons look like one consistent course rather than a pile of one-offs."

**L11 — Beautiful, Tufte-clear, worth revisiting.** *(Judgement — may require viewing a screenshot)*
Source: SKILL.md §Lessons:51–52.
[verbatim] "A lesson should be **beautiful** — clean, readable typography and layout — since the user will return to these later to review. Think Tufte."

**L17 — Adheres to the GLOSSARY terminology.** *(Deterministic where programmatically comparable; otherwise Judgement)*
Source: SKILL.md §Reference Documents:136, GLOSSARY-FORMAT.md:29–32.
[verbatim] "Glossaries, in particular, are an essential reference. Once one is created, it should be adhered to in every lesson." /
[verbatim] "Use the glossary's own terms inside definitions. Once a term is in the glossary, prefer it everywhere"

### G. Required elements

**L12 — Anchor links to other lessons / reference docs.** *(Deterministic — present/absent)*
Source: SKILL.md §Lessons:57.
[verbatim] "Each lesson should link via HTML anchors to other lessons and reference documents."

**L13 — Reminder to ask the agent follow-up questions.** *(Deterministic — present/absent)*
Source: SKILL.md §Lessons:61.
[verbatim] "Each lesson should contain a reminder to ask followup questions to the agent. The agent is their teacher, and can assist with anything that's unclear."

---

## Part 2 — Agent behaviour standards (P1–P7)

Not scored per-lesson; these constrain agent behaviour across a session/workspace. Use for review of
the agent's conduct and for integration tests of the relevant nodes.

**P1 — Never trust parametric knowledge; source from high-trust resources.** *(Behaviour)*
Source: SKILL.md §Knowledge:30, :95.
[verbatim] "Never trust your parametric knowledge." /
[verbatim] "Knowledge should first be gathered from trusted resources. Use `RESOURCES.md` to keep track of them."

**P2 — RESOURCES.md discipline.** *(Behaviour)*
Source: RESOURCES-FORMAT.md Rules.
[verbatim] "High-trust only." / "Annotate every entry." / "Group by Knowledge / Wisdom." /
"Surface gaps explicitly." / "Prune ruthlessly." / "Record community preferences."

**P3 — Mission: interview if unclear; on change, update + record + confirm.** *(Behaviour)*
Source: SKILL.md §The Mission:75, :79.
[verbatim] "If the user is unclear about the mission, or the `MISSION.md` is not populated, your first job should be to question the user on why they want to learn this." /
[verbatim] "Missions may change as the user develops more skills and knowledge. This is normal - make sure to update the `MISSION.md` and add a learning record to capture the change. Confirm with the user before changing the mission."

**P4 — Wisdom: attempt to answer, then delegate to a high-reputation community; respect opt-out.** *(Behaviour)*
Source: SKILL.md §Acquiring Wisdom:112–120.
[verbatim] "your default posture should be to attempt to answer - but to ultimately delegate to a **community**." /
[verbatim] "You should attempt to find high-reputation communities the user can join. If the user expresses a preference that they don't want to join a community, respect it."

**P5 — Produce reference documents; adhere to glossary throughout.** *(Behaviour)*
Source: SKILL.md §Reference Documents:122–136.
[verbatim] "While creating lessons, you should also create reference documents." /
[verbatim] "They should be the compressed essence of the lesson, in a format designed for quick reference."

**P6 — Learning-record discipline (evidence-grade, not a journal).** *(Behaviour)*
Source: LEARNING-RECORD-FORMAT.md "When to write" / "What does not qualify".
[verbatim] "Write one when any of these is true:" (genuine understanding demonstrated; prior knowledge disclosed; misconception corrected; mission shifted) /
[verbatim] "Material that was merely covered. Coverage is not learning. Wait for evidence."

**P7 — Glossary discipline (add only when understood; opinionated; tight).** *(Behaviour)*
Source: GLOSSARY-FORMAT.md Rules.
[verbatim] "Add a term only when the user understands it." /
[verbatim] "Be opinionated." / [verbatim] "Keep definitions tight."

---

## Source coverage note [ours]

L1–L17 + P1–P7 constitute the full audit of judgement/behaviour standards in `teach/SKILL.md` and the
four FORMAT files. Deterministic items (L6, L7, L9, L12, L13, and L17 where comparable) are enforced by
the mechanical validation step (ADR-0006) rather than by a judge. SKILL.md frontmatter is Claude-Code
host configuration with no standalone equivalent (`disable-model-invocation` dropped; `argument-hint`
repurposed as a conversation opener) and contributes no scoring criteria.
