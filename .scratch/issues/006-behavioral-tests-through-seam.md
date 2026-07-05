# 006 — Re-establish behavioral tests through the single seam

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

Re-establish the test suite around the one seam, `runner.invoke_turn`, using the seeded-fixture pattern as the canonical prior art for all future tests (`PRD.md` §Testing Decisions).

Tests assert **external behavior only**: given a seeded Workspace fixture and a user message, a Turn produces the right artifact files and an appropriate reply. Tests never assert on internal control flow, node transitions, or intermediate structured outputs — those are exactly the internals #003 deletes.

Cover, through the seam, the end-to-end Turn behaviors:

- Mission interview when `MISSION.md` is absent/vague — the Turn ends with a question.
- Research when `RESOURCES.md` is sparse.
- Lesson creation and file commit to `lessons/`.
- Reference / glossary / learning-record writes under their stated conditions.
- Mission-change confirm-and-record (updates `MISSION.md` + adds a learning record).
- `spawn_topic` handoff on a brand-new topic.

Keep these **deterministic behavioral tests** distinct from the subjective-quality eval (#005): "did a Lesson file get written / did the interview Turn end with a question" lives here; "is the Lesson good" lives in the offline LLM-judge eval, not in unit tests.

Where a behavior depends on model output that is expensive or nondeterministic, drive the seam with a stub/fake model (via the existing `models`/`get_model` seam or an injected agent) so tests stay hermetic — but still assert only on external artifacts and replies.

## Acceptance criteria

- [ ] All tests drive `runner.invoke_turn` (the single seam) with a seeded Workspace fixture + a user message.
- [ ] Tests assert only on external behavior (artifact files written, reply shape), never on internal control flow or intermediate structured outputs.
- [ ] Coverage includes: interview-when-Mission-absent, research-when-RESOURCES-sparse, lesson commit, reference/glossary/learning-record writes, mission-change confirm+record, and `spawn_topic` handoff.
- [ ] Tests are hermetic (temp Workspace root; model calls stubbed/faked where needed) and pass in CI without live model keys.
- [ ] The fixture + `invoke_turn` layout is documented as the canonical pattern for future tests.

## Blocked by

- #003

## Comments
