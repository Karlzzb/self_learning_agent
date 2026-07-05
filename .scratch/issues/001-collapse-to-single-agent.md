# 001 — Collapse the teaching graph into a single ReAct agent

Status: ready-for-agent
**Type:** AFK

## Blocked by

_(none)_

## Summary

Replace the 16-node LangGraph teaching orchestration with **one general ReAct agent**
(`create_react_agent`) driven by faithfully-ported `teach` prose plus a minimal tool set,
and move all quality control into an **offline, black-box eval**.
Net-negative lines is the acceptance criterion.

Full spec: `PRD.md` (root). Read it first — this ticket is the execution checklist.

## Why

The same free models teach well when running `teach` prose inside Claude Code's general
agent loop; the port's rigid state machine is the regression. See `PRD.md` §Problem Statement.

## Tasks (in order)

1. **Build the single agent.**
   New module assembling `create_react_agent`: system prompt = ported `teach` SKILL.md prose
   (adapted for the server: available tools, workspace paths, turn-boundary questions);
   tools = workspace file read/write/list/glob, swappable web search, open-file.

2. **Add the `[ours]` interview prose** to the system prompt: gather purpose → level → constraints;
   offer concrete options as a tactic (not a hard rule).

3. **Rewire the shell to call the agent.**
   Keep `runner.invoke_turn` as the kernel/seam; simplify `state.py` to messages + tenancy keys
   + artifact diff; keep `spawn_topic`. Delete all `interrupt()`/resume plumbing (turn-boundary
   questions instead). Keep `api.py`/`cli.py` as thin drivers, Langfuse callbacks, multi-tenancy.

4. **Delete the regressive internals.**
   `graph.py`, `lesson.py`, `validators.py`, `scoring.py`, `mission.py`, `zpd.py`,
   `assessment.py`, `wisdom.py`, `research.py`, `reference.py`, `new_topic.py`, and the bulk of
   `prompts.py`. Fold `language.py`/`sanitize.py` into helpers if trivial, else delete.

5. **Simplify `config.py` and `models.py`** to a single primary model knob (still swappable to Claude).

6. **Retire superseded docs in the same change:**
   ADR-0001, 0005, 0006, 0008, 0010, 0011; rewrite/retire ADR-0009 and ADR-0013;
   rewrite `CODE.md` and `docs/config.md` to the single-agent design.

7. **Extend `RUBRIC.md`** with one interview item scored on outcome
   ("could a competent teacher write MISSION.md and pick the first Lesson from what was gathered?").

8. **Build the offline eval harness** (separate `eval/` dir, zero runtime imports):
   drives `invoke_turn` over seeded workspace fixtures, LLM-judges Lesson artifacts and interview
   Turns against `RUBRIC.md`, logs to Langfuse. Plain Python script — no promptfoo/framework.
   Include a README encoding the discipline: human-label ground truth → tune judge to agree →
   freeze rubric → iterate prompt only.

9. **Re-establish tests** through the single seam `runner.invoke_turn`: seeded fixture + user
   message → assert artifact files + reply. No assertions on internal control flow.

## Acceptance

- `src/` is materially smaller; no graph, no lesson subgraph, no validators, no interrupts.
- A Turn through `invoke_turn` runs the mission interview → research → lesson flow via the one agent.
- Offline eval produces scores in Langfuse for at least the Lesson and interview units.
- No superseded ADR/doc still describes the removed architecture as current.

## Out of scope

Routing/session eval (phase 2); any runtime quality gate; auth/accounts/billing;
`CONTEXT-MAP.md` split. See `PRD.md` §Out of Scope.

## Comments
