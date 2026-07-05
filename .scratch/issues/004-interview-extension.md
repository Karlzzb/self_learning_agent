# 004 — `[ours]` interview extension: purpose → level → constraints

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

Add the one sanctioned `[ours]` capability extension: explicit interview guidance the source `teach` skill is silent on.

`teach` only says "your first job should be to question the user on why they want to learn this." Inside Claude Code the crisp interview (concrete options, one round for *purpose* then one for *current level*) is Claude improvising well; free models do not improvise it, which then poisons the Mission, the ZPD, and every downstream Lesson (`PRD.md` §Problem Statement, §Further Notes).

Two pieces:

- **Interview prose** added to the agent's system prompt (the seam left by #003): when the Mission is absent or vague, gather **purpose**, then **current level**, then **constraints**. Offer concrete options as a *tactic* to reduce ambiguity. These are authoring tactics, **not** rubric law — do not encode "must have N options" or "must be 2 rounds."
- **One interview item in `RUBRIC.md`**, scored on **outcome**, not tactics: "given the gathered information, could a competent teacher write `MISSION.md` and select the first Lesson from it?" Keep it consistent with the existing L-item / P-item structure so the eval (#005) can score it as its own unit.

From the learner's point of view the interview arrives as ordinary chat Turns (turn-boundary questions from #003) — no special UI.

## Acceptance criteria

- [ ] The system prompt contains explicit interview guidance: gather purpose → current level → constraints, with concrete options framed as a tactic (not a hard rule).
- [ ] Given a seeded Workspace with no/ vague `MISSION.md`, a Turn ends with a purpose-seeking question, and over a short exchange gathers enough to write a `MISSION.md` and make a first-Lesson choice.
- [ ] `RUBRIC.md` gains exactly one interview item, scored on information-sufficiency outcome, phrased so an LLM judge can apply it against a single interview Turn.
- [ ] The rubric item measures the outcome, not the tactics — no "N options" / "N rounds" requirements.

## Blocked by

- #003

## Comments
