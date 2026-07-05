# 002 — Prefactor: make the runner seam compute artifacts independently of the graph

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

A prefactor that makes `runner.invoke_turn`'s output contract independent of *what runs inside* the invocation, so the later single-agent swap (#003) is a clean drop-in.

Today the turn's `new_artifacts` list is produced inside the graph (a finalize node writes it into graph state) and the runner just reads `result["new_artifacts"]`.
Change it so the runner itself snapshots the workspace directory before the invocation and diffs it afterward — using the existing deterministic `workspace.scan_files` / `workspace.diff_new` primitives — to derive the artifacts produced this Turn.

This is "make the change easy, then make the easy change": after this prefactor the seam reports artifacts by observing the filesystem (the single source of truth, ADR-0003), so #003 can replace the graph with the agent without touching how a Turn reports its output.

Behavior is unchanged for the end user: the same Turn still returns the same reply and the same set of new artifacts — only the *source* of the artifact list moves from graph state to a runner-side workspace diff.
Do not remove interrupts, nodes, or graph wiring here; that is #003.

Avoid layer-by-layer churn: keep `state.py`, the graph, and `api.py`/`cli.py` behaviorally intact except for the artifact-sourcing move.

## Acceptance criteria

- [ ] `runner.invoke_turn` computes `new_artifacts` by diffing the workspace (baseline snapshot before invocation vs. current snapshot after) via `workspace.scan_files` / `workspace.diff_new`, not by reading it out of graph state.
- [ ] A Turn returns the same reply and the same `new_artifacts` set it did before the prefactor (verified through `invoke_turn`).
- [ ] Internal workspace meta files (e.g. `workspace.json`) remain excluded from the reported artifacts, matching current `diff_new` behavior.
- [ ] The graph, its nodes, interrupts, and `spawn_topic` handoff still function exactly as before; no node/module deletions in this slice.
- [ ] `spawn_topic` is still surfaced on `TurnResult` unchanged.

## Blocked by

None - can start immediately.

## Comments
