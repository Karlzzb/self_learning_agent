# PRD — Collapse the teaching orchestration into a single agent

> Standalone spec.
> A fresh session can start from this file alone.
> It supersedes the previous graph-based design.
> See `OVERVIEW.md` for the doc map and the list of superseded documents.

## Problem Statement

The standalone port teaches worse than the original `teach` skill running inside Claude Code.

This is not a model problem.
The same free models (Qwen, MiMo, MiniMax) produce excellent tuition when they run the `teach` prose inside Claude Code's general agent loop.
Claude Code *is* an orchestration layer — a general reason–act loop (read files, reason, write files, run a command, repeat) — and the `teach` skill is just prose injected into it.

The port replaced that single fluid loop with a rigid state machine.
It shattered one agent into a 16-node LangGraph: an 11-node teaching graph (`router → {mission | research | zpd | lesson → reference | assessment | wisdom | new_topic} → finalize`) plus a 5-node lesson subgraph (`draft → validate → critique → decide → rewrite`).
On top of that sit a deterministic router, a 556-line `validators.py`, ~10 Pydantic lesson schemas, and four `interrupt()` points.

Three concrete harms follow:

1. **Quality regression.** Every fixed rail is a place the port can be dumber than the free-flowing skill.
   The rigid router, the forced validate/critique/rewrite gate, and the per-node structured-output decomposition constrain the model into worse output than it produces when left to reason fluidly.
2. **Unmaintainable.** ~7,180 lines across 24 modules, dominated by `prompts.py` (1,381) and `lesson.py` (917).
   The owner is stuck tuning the graph rather than the teaching.
3. **Eval could not attach.** A prior attempt (rubric + promptfoo) failed because it bolted an eval onto an already-complex runtime and made the whole thing worse.

A specific, faithful-porting failure compounds this: the mission interview.
In Claude Code the interview feels crisp — concrete options, one round for *purpose* then one for *current level*.
But `teach` never specifies that; SKILL.md says only "your first job should be to question the user on why they want to learn this."
The crisp interview is Claude improvising well.
Free models do not improvise it from one thin sentence, so the port's information-gathering is weak, which then poisons the Mission, the ZPD, and every Lesson downstream.

## Solution

Collapse the entire teaching graph into **one general ReAct agent**, and move all quality control **offline**.

From the learner's point of view nothing about the pedagogy changes — Mission-driven teaching, ZPD, Knowledge/Skills/Wisdom, Lessons, reference docs, glossary, learning records all remain.
What changes is that a single agent, driven by faithfully-ported `teach` prose plus a small tool set, navigates the Workspace fluidly — exactly as the skill does inside Claude Code — instead of being marched through fixed nodes.

Core moves:

- **One agent, not a graph.**
  A single ReAct agent (LangGraph `create_react_agent`) whose system prompt is the ported `teach` prose and whose tools are file read/write/list/glob, web search, and open-file.
  Mission establishment, research, ZPD selection, lesson authoring, reference building, assessment, and wisdom stop being nodes; they become things the prose tells the one agent to do — as in the source skill.

- **Turn-boundary questions; no mid-turn interrupts.**
  When the agent needs information (unclear Mission, unknown level), it ends the Turn *with* a question, and the learner's next message is simply the next Turn.
  The Workspace files carry state across Turns, so the agent re-derives "where am I" by reading `MISSION.md` / `learning-records/` — it never resumes a suspended stack.
  All four `interrupt()` sites and the resume plumbing are deleted.

- **No runtime quality gate.**
  The agent writes Lesson HTML directly via the write tool, like `teach`.
  The `draft → validate → critique → decide → rewrite` subgraph, `validators.py`, the critique call, and the Pydantic lesson schemas are deleted.
  A free model can now commit an imperfect Lesson; the safety net is the offline eval catching systematic badness so the prose gets fixed — not a per-Lesson runtime guard.

- **Quality lives in exactly one place: an offline, black-box eval.**
  The eval shares zero code with the runtime.
  It drives the same `runner.invoke_turn` a real user hits, reads the artifact files that come out, LLM-judges them against `RUBRIC.md`, and logs to Langfuse.
  When a Lesson or interview is bad, the fix is the **prose or the rubric**, then re-eval — never a new runtime gate.

- **Add an explicit `[ours]` interview spec.**
  Because `teach` is silent on interview quality, add explicit prose guidance (offer concrete options as a tactic; gather *purpose*, then *current level*, then *constraints*) plus a matching outcome-based rubric item.
  The rubric measures the *outcome* — "could a competent teacher write `MISSION.md` and pick the first Lesson from what was gathered?" — not the tactics (never "must have 4 options" or "must be 2 rounds").

- **Keep the essential shell.**
  `runner.invoke_turn` (the kernel and single test seam), Workspace-as-files (files are the memory, not graph state), multi-tenancy, Langfuse callbacks, the `spawn_topic` handoff, and turn-end artifact diffing all stay.

- **Net-negative lines is the acceptance criterion.**
  Every change deletes code/docs or is load-bearing for the single-agent spine.
  Superseded ADRs and design docs are retired in the same change as the code they describe, so no archaeology confuses the next reader.

## User Stories

1. As a learner, I want the agent to interview me about *why* I want to learn a topic before teaching, so that every Lesson is grounded in my real-world Mission.
2. As a learner, I want the interview to offer concrete options rather than open-ended vague prompts, so that I can answer quickly and precisely.
3. As a learner, I want the agent to ask about my current level after my purpose, so that the first Lesson lands in my Zone of Proximal Development.
4. As a learner, I want a follow-up question to arrive as the natural next thing the agent says (a normal chat turn), so that the conversation feels continuous without special UI.
5. As a learner, I want each Lesson to be a short, self-contained HTML file tied to my Mission, so that I get one tangible win within my working-memory budget.
6. As a learner, I want Lessons to reuse existing assets and cite trusted sources, so that quality and consistency hold across sessions.
7. As a learner, I want the agent to find high-quality external resources before relying on its own parametric knowledge, so that I learn correct material.
8. As a learner, I want reference cheat-sheets built alongside Lessons, so that I can look things up quickly later.
9. As a learner, I want a glossary that records terms only once I can use them correctly, so that it reflects compressed understanding, not vocabulary to cram.
10. As a learner, I want the agent to write a learning record only when I demonstrate genuine understanding, disclose prior knowledge, correct a misconception, or my Mission shifts, so that records stay meaningful rather than logging every session.
11. As a learner, I want to be able to change my Mission, with the agent confirming, updating `MISSION.md`, and recording the change, so that my learning re-grounds when my goals evolve.
12. As a learner, I want to start a brand-new topic and have the agent hand off cleanly into a fresh Workspace, so that topics stay isolated.
13. As a learner, I want to ask a practitioner-level "wisdom" question and get an answer that ultimately points me to a community, so that I learn where expertise really lives.
14. As a learner, I want the agent to reply in my Workspace language, so that lessons and questions feel native.
15. As an API integrator, I want a single `POST /chat` turn endpoint driving the same kernel as the CLI, so that both surfaces behave identically.
16. As an API integrator, I want each Turn to report the artifacts it produced, so that I can surface new Lessons/references to my UI.
17. As an API integrator, I want multi-tenant isolation by `user_id` and topic, so that learners never see each other's Workspace.
18. As an agent developer, I want the whole teaching flow to be one agent + prose + a few tools, so that I tune teaching quality by editing prose, not by rewiring a graph.
19. As an agent developer, I want no runtime validate/critique/rewrite machinery, so that the agent writes fluidly and there is far less code to maintain.
20. As an agent developer, I want an offline eval that treats the agent as a black box through `invoke_turn`, so that adding eval never adds runtime complexity.
21. As an eval author, I want to score the produced Lesson HTML against `RUBRIC.md` with an LLM judge over seeded Workspace fixtures, so that I get a reproducible quality signal.
22. As an eval author, I want to score the interview Turn (given unknown Mission/level, is the gathered information sufficient?) as a separate unit, so that interview failures are isolated from Lesson failures.
23. As an eval author, I want eval scores logged to Langfuse, so that I can track quality across prompt iterations over time.
24. As an agent developer, I want to first tune the judge until it agrees with my own human labels and then freeze it, so that I can subsequently attribute score changes to prompt changes alone.
25. As an agent developer, I want the rubric held stable while I iterate the prompt, so that I never confuse "I changed the yardstick" with "I improved the agent."
26. As a maintainer, I want the redesign to delete more than it adds — including retiring ADRs and docs for the removed graph — so that the project becomes easier to read.
27. As a new contributor, I want `OVERVIEW.md` and `PRD.md` to describe only the current single-agent design, so that I am never misled by documentation of the removed architecture.

## Implementation Decisions

### Runtime architecture

- **Single ReAct agent.**
  Replace the teaching graph and lesson subgraph with one `create_react_agent`.
  Its system prompt is the ported `teach` prose; its tools are the minimal set below.
  This is deliberately the simplest LangGraph construct, which also lowers the graph-tuning burden that currently blocks the owner.
- **Tools (minimal, swappable).**
  Workspace file operations (read, write, list, glob), a swappable web-search tool, and open-file.
  Retain the swappable-search principle from ADR-0007.
  No tool performs teaching judgment; judgment lives in the prose.
- **Turn-boundary interaction.**
  The agent asks by ending a Turn with a question; the next user message is the next Turn.
  Remove all `interrupt()`/resume plumbing.
  This removes the `temperature=0.0`-for-replay constraint currently forced on pre-interrupt decisions.
- **State shrinks to essentially messages plus tenancy keys.**
  With one agent, per-node handoff fields (`next_lesson_scope`, `last_lesson`, `intent`, interview scratch) disappear.
  Keep `user_id`, `topic`/`topic_slug`, and the turn-end artifact diff (`baseline_files` → `new_artifacts`).
  `spawn_topic` remains as the driver handoff signal.
- **Workspace-as-files stays (ADR-0003).**
  Files under `workspaces/{user_id}/{topic_slug}/` remain the single source of truth and the cross-Turn memory.
- **Model configuration simplifies.**
  Per-node model tiering collapses toward a single primary model knob (still swappable to Claude or a free model), since there is now one agent.
  `models.get_model` remains the only place the model is chosen.
- **Failure posture is revisited.**
  The previous "refuse rather than degrade" posture (ADR-0009) was tied to the deleted runtime gate.
  Without a gate, the agent produces output and the offline eval catches systematic problems.
  ADR-0009 is retired or rewritten accordingly.

### Interview (`[ours]` extension)

- Add explicit interview prose to the system prompt: gather **purpose**, then **current level**, then **constraints**; offer concrete options as a *tactic* to reduce ambiguity.
- These are authoring tactics, not rubric law.
- Add one interview rubric item scored on **outcome**: is the gathered information sufficient and unambiguous enough to write `MISSION.md` and select the first Lesson?

### Offline eval harness

- **Black-box only.**
  The harness imports nothing from the graph/runtime internals; it calls `runner.invoke_turn` (or the HTTP API), reads artifact files, and judges them.
- **Two units.**
  (1) Lesson artifact judged against `RUBRIC.md` L-items.
  (2) Interview Turn judged against the new information-sufficiency item.
  Both are single-shot: one seeded fixture in, one artifact/question out, one score vector.
- **Fixtures.**
  Seeded Workspace directories checked into the repo (a `MISSION.md`, some `learning-records/`, optionally `RESOURCES.md`) plus a user message.
- **Plain script, not a framework.**
  A small Python runner loops fixtures and pushes scores to Langfuse.
  Do not reintroduce promptfoo or any eval framework in the runtime.
- **Methodology discipline (encode in the eval README, not code):**
  human-label ~10 lessons/interviews as ground truth → tune the judge/rubric until it agrees with the human → **freeze the rubric** → then iterate only the prompt, using the frozen judge as the yardstick.
  Never move rubric and prompt in the same step.
- **Routing/session eval is phase 2.**
  Artifact + interview eval ship first.
  Decision-quality eval (did it route correctly) and simulated multi-turn learner sessions are added later only if Langfuse logs show routing is where quality breaks.

### Prune list (delete in the same change as the code)

Code to delete outright:
`graph.py`, `lesson.py`, `validators.py`, `scoring.py`, `mission.py`, `zpd.py`, `assessment.py`, `wisdom.py`, `research.py`, `reference.py`, `new_topic.py`, and the bulk of `prompts.py`.
Their behavior moves into the single system prompt and the tool set.
Evaluate `language.py` and `sanitize.py` for folding into prose/tool helpers rather than standing modules.

Code to keep and simplify:
`runner.py` (kernel/seam), `api.py`, `cli.py` (thin drivers), `config.py` (fewer knobs), `models.py`, `workspace.py` (file helpers backing the tools), `tenancy.py`, `observability.py` (Langfuse), `search.py` (web-search tool), `state.py` (shrunk).
Add one new module assembling the agent (system prompt + tools + `create_react_agent`).

Docs to retire (describe the removed architecture):
ADR-0001 (structured-pedagogy-graph), ADR-0005 (single-graph-no-supervisor), ADR-0006 (lesson-authoring-node), ADR-0010 (turn-cascade-in-graph-edges), ADR-0011 (first-lesson-menu-and-new-topic-handoff), ADR-0008 (already superseded by 0016).
Revisit ADR-0009 (failure posture) and ADR-0013 (workspace-language) — rewrite to the single-agent reality or retire.
Rewrite `CODE.md`, `docs/config.md`, and `OVERVIEW.md` to the single-agent design.

Docs to keep:
ADR-0003 (files-as-source-of-truth), ADR-0004 (api-only-product-no-identity), ADR-0007 (minimal-tools-swappable-search), ADR-0012 (memory layer — verify it adds no runtime machinery beyond files), ADR-0016 (Langfuse).
`CONTEXT.md` (glossary) and `RUBRIC.md` (extended with the interview item).

## Testing Decisions

- **What a good test is.**
  Tests assert external behavior only: given a seeded Workspace fixture and a user message, a Turn produces the right artifact files and an appropriate reply.
  Tests never assert on internal control flow, node transitions, or intermediate structured outputs — those are exactly the internals being deleted.
- **Single seam.**
  All tests drive `runner.invoke_turn`.
  It is already the kernel behind both CLI and API, and it is what the eval harness uses, so there is one seam across the entire codebase.
- **Modules under test (through the seam):**
  the assembled agent's end-to-end Turn behavior — mission interview when `MISSION.md` is absent/vague, research when `RESOURCES.md` is sparse, Lesson creation and file commit, reference/glossary/learning-record writes under their stated conditions, mission-change confirm-and-record, and `spawn_topic` handoff on a new topic.
- **Eval vs. tests are distinct.**
  Deterministic behavioral tests (did a Lesson file get written; did the interview Turn end with a question when Mission is unknown) live in the test suite.
  Subjective quality (is the Lesson good) lives in the offline LLM-judge eval, not in unit tests.
- **Prior art.**
  The prior test layout was removed and is being redefined; establish the seeded-fixture + `invoke_turn` pattern as the canonical prior art for all future tests.

## Out of Scope

- Changing the pedagogy.
  Mission/ZPD/Knowledge-Skills-Wisdom/Lessons/reference/glossary/learning-records are ported faithfully, not redesigned.
- Any runtime quality gate, validator, or critique/rewrite loop.
  Explicitly removed, not relocated.
- Routing-quality eval and simulated multi-turn session eval (phase 2).
- A new eval framework (promptfoo or otherwise) in the runtime.
- Authentication, accounts, and billing (ADR-0004 unchanged — the agent stays identity-agnostic).
- Multi-context glossary split (`CONTEXT-MAP.md`); the single `CONTEXT.md` remains until contexts actually split.

## Further Notes

- The central thesis to hold onto: a *general* agent loop plus the `teach` prose already produces great tuition on free models; the port's rigidity is the regression.
  The redesign restores the general loop and keeps only the shell that makes it an independently operable, API-callable service.
- The interview is the one place where "faithful porting" would reproduce a weakness, because the good behavior was Claude improvising over a silent spec.
  This is the only sanctioned `[ours]` capability extension.
- Guard against re-growth: if a change adds a node, a runtime gate, or a second orchestration layer, it is almost certainly wrong.
  The eval, not the runtime, is where quality pressure is applied.
