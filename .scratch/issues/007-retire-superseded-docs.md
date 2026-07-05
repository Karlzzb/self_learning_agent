# 007 — Retire superseded docs & finish the single-agent doc set

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

Make the documentation describe only the current single-agent design, so no reader is misled by documentation of the removed graph architecture (`PRD.md` §Prune list, US 26–27).

Most superseded ADRs are already deleted (only ADR-0002, 0003, 0004, 0007, 0012, 0016 remain). What is left:

- **Rewrite `CODE.md`, `docs/config.md`, and `OVERVIEW.md`** to the single-agent design: one ReAct agent + prose + a few tools, turn-boundary questions, the single model knob, the `eval/` harness, and the seeded-fixture + `invoke_turn` test pattern.
- **Verify no remaining doc or ADR** still describes the removed graph / lesson subgraph / validators / interrupts / per-node model tiering as current. Reconcile any surviving references (including in the kept ADRs and `docs/agents/`) against the collapsed architecture — rewrite or retire as needed. ADR-0009 (failure posture) and ADR-0013 (workspace language) were tied to the deleted gate/node fragmentation; confirm they are retired or rewritten to the single-agent reality.
- **Record the net-negative-lines accounting** for the redesign (`PRD.md` §Solution): the redesign should delete more than it adds across code + docs.

Keep: `CONTEXT.md` (glossary) and `RUBRIC.md` (extended by #004); ADR-0002/0003/0004/0007/0012/0016.

## Acceptance criteria

- [ ] `CODE.md`, `docs/config.md`, and `OVERVIEW.md` describe only the single-agent design (no graph, lesson subgraph, validators, interrupts, or per-node tiering presented as current).
- [ ] A sweep confirms no surviving doc/ADR describes the removed architecture as current; any stray references are rewritten or removed.
- [ ] ADR-0009 and ADR-0013 are confirmed retired or rewritten to the single-agent reality.
- [ ] The net-negative-lines accounting for the redesign is recorded.
- [ ] `CONTEXT.md`, `RUBRIC.md`, and the kept ADRs remain intact.

## Blocked by

- #003

## Comments
