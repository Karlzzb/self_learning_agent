# Structured pedagogy graph over a thin ReAct agent

When porting the `teach` skill to LangGraph, we decided to model the agent as a **structured pedagogy graph** — a coarse-grained graph with one node per teaching *capability* (Router, Mission intake, Research, ZPD/planning, Lesson authoring, Assessment, Record-keeping), each node internally a "fat prompt" — rather than a single thin `create_react_agent` that does everything via in-context reasoning.

## Considered Options

- **Thin graph / fat prompt** (`create_react_agent` + tools): fastest and closest to today's Claude Code behavior, but no per-stage observability, no way to independently tune or re-model a single teaching stage, and little LangGraph learning value.
- **Structured pedagogy graph (chosen):** explicit capability nodes mapped 1:1 onto `teach`'s existing file artifacts (the file formats become the state schema). Costs more upfront design and risks over-decomposition.

## Consequences

- Strict discipline: decompose **by capability/phase, not by micro-step**, to avoid slicing up `teach`'s fluid pedagogical judgment.
- Each node can bind a different model tier (per-node model routing) and be observed/tuned independently — directly serving the "mature + continuously tunable" goal.
- The graph models the **macro curriculum loop**; the in-lesson micro feedback loop is handled separately (see ADR-0002).
