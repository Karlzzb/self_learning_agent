# 003 — Collapse the teaching graph into one ReAct agent

Status: ready-for-agent
**Type:** AFK

## Parent

- #001

## What to build

Replace the entire 16-node teaching graph (and 5-node lesson subgraph) with **one general ReAct agent** (`create_react_agent`) driven behind the same `runner.invoke_turn` seam.
This is the spine of the redesign; see `PRD.md` §Solution and §Implementation Decisions.

End-to-end behavior of a Turn after this slice:

- One agent, one Turn. The learner's message goes in; the agent reads/writes Workspace files fluidly (as `teach` does inside Claude Code) and returns a reply plus the artifacts it produced (the runner-side diff from #002).
- **Turn-boundary questions, no interrupts.** When the agent needs information it ends the Turn *with* a question; the learner's next message is simply the next Turn. State is re-derived by reading Workspace files, never by resuming a suspended stack.
- The full ported pedagogy still emerges — Mission-grounded teaching, ZPD, Knowledge/Skills/Wisdom, lessons, reference docs, glossary, learning records, mission-change confirm-and-record, `spawn_topic` handoff, Workspace language — but as things the *prose* tells the one agent to do, not as nodes.

Concretely:

- **New agent module** assembling `create_react_agent`: system prompt = the faithfully-ported `teach` SKILL.md prose (and the FORMAT files it references), adapted for the server — the tools that exist, the Workspace paths, and the turn-boundary-question convention in place of mid-turn interrupts. (The `[ours]` interview prose is a separate slice, #004 — leave a clear seam for it.)
- **Tools (minimal, swappable):** Workspace file read / write / list / glob, open-file, and the existing swappable web search (`search.py`, ADR-0007). No tool performs teaching judgment.
- **`spawn_topic` handoff** is preserved end-to-end: give the agent a way to signal a brand-new out-of-domain topic, the runner surfaces it on `TurnResult`, and `api.py`/`cli.py` re-invoke on the new topic (existing driver logic).
- **Rewire the shell:** `runner.invoke_turn` drives the agent; delete all `interrupt()` / `Command(resume=...)` / pending-interrupt plumbing. Shrink `state.py` to messages + tenancy keys (`user_id`, `topic`, `topic_slug`) + the artifact-diff bookkeeping. Keep `api.py` / `cli.py` as thin drivers, Langfuse callbacks, and multi-tenancy.
- **Single model knob:** simplify `config.py` / `models.py` from per-node tiering to one primary model (still swappable to Claude or a free model); `models.get_model` stays the only place the model is chosen.
- **Delete the regressive internals** in this same change: `graph.py`, `lesson.py`, `validators.py`, `scoring.py`, `mission.py`, `zpd.py`, `assessment.py`, `wisdom.py`, `research.py`, `reference.py`, `new_topic.py`, and the bulk of `prompts.py`. Fold `language.py` / `sanitize.py` into small helpers if trivially load-bearing, else delete. Keep `workspace.py`, `tenancy.py`, `observability.py`, `search.py`.

Net-negative lines is the acceptance criterion (`PRD.md` §Solution): every change deletes code or is load-bearing for the single-agent spine.

## Acceptance criteria

- [ ] A new module assembles `create_react_agent` with the ported `teach` prose as system prompt and the minimal tool set (workspace read/write/list/glob, open-file, swappable web search).
- [ ] A Turn through `invoke_turn` runs the mission-interview → research → lesson flow via the one agent and writes a lesson HTML file to `lessons/`, reported in `new_artifacts`.
- [ ] When the Mission is unknown/vague, the Turn ends with a question (no `interrupt()` anywhere); the next message continues as a normal Turn.
- [ ] `graph.py`, the lesson subgraph, `validators.py`, and all four interrupt sites are gone; `git grep` finds no `interrupt(` / `Command(resume` in `src/`.
- [ ] `state.py` is reduced to messages + tenancy + artifact-diff fields; per-node handoff fields (`next_lesson_scope`, `last_lesson`, `intent`) are removed.
- [ ] `config.py` / `models.py` expose a single primary model knob (no per-node tier table) and remain swappable to Claude.
- [ ] `spawn_topic` handoff still works: a new out-of-domain topic produces a `spawn_topic` on `TurnResult` and the driver continues into the new topic's interview.
- [ ] `src/` is materially smaller (net-negative lines); the prune list above is deleted, not relocated.

## Blocked by

- #002

## Comments
