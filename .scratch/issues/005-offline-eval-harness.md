# 005 — Offline black-box eval harness

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

Move all quality control offline into a single black-box eval that shares **zero code** with the runtime (`PRD.md` §Offline eval harness).
It drives the same `runner.invoke_turn` a real user hits, reads the artifact files that come out, LLM-judges them against `RUBRIC.md`, and logs to Langfuse. When a Lesson or interview is bad, the fix is the **prose or the rubric**, then re-eval — never a new runtime gate.

- **Black-box only.** A separate `eval/` directory that imports nothing from the agent/runtime internals; it calls `invoke_turn` (or the HTTP API), reads artifact files, and judges them.
- **Two units, both single-shot** (one seeded fixture in, one artifact/question out, one score vector):
  1. **Lesson artifact** judged against `RUBRIC.md` L-items.
  2. **Interview Turn** judged against the information-sufficiency item added in #004.
- **Fixtures:** seeded Workspace directories checked into the repo (a `MISSION.md`, some `learning-records/`, optionally `RESOURCES.md`) plus a user message.
- **Plain Python script, not a framework.** A small runner loops fixtures and pushes scores to Langfuse. Do **not** reintroduce promptfoo or any eval framework.
- **README encoding the methodology discipline** (in prose, not code): human-label ~10 lessons/interviews as ground truth → tune the judge/rubric until it agrees with the human → **freeze the rubric** → then iterate only the prompt, using the frozen judge as the yardstick. Never move rubric and prompt in the same step.
- **Out of scope (phase 2):** routing/decision-quality eval and simulated multi-turn learner sessions — add later only if Langfuse logs show routing is where quality breaks.

## Acceptance criteria

- [ ] `eval/` exists and imports nothing from the graph/agent/runtime internals — it reaches the system only through `invoke_turn` (or the HTTP API) and by reading artifact files.
- [ ] The Lesson unit scores a produced Lesson HTML against `RUBRIC.md` L-items over at least one seeded fixture and emits a score vector.
- [ ] The interview unit scores an interview Turn against the information-sufficiency item over at least one seeded fixture and emits a score vector.
- [ ] Both units' scores are logged to Langfuse.
- [ ] Seeded Workspace fixtures are checked into the repo.
- [ ] An eval README documents the human-label → tune-judge → freeze-rubric → iterate-prompt discipline.
- [ ] No eval framework (promptfoo or otherwise) is added to the runtime.

## Blocked by

- #003
- #004

## Comments
