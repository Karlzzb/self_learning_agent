# Single graph with capability nodes; no supervisor / multi-agent (MVP)

We deliberately do **not** adopt the `langgraph-supervisor` / multi-agent pattern that early LangGraph reference notes recommended as "production first choice." The agent is **one graph with capability nodes** (Router + the teaching phases). A capability may later be promoted to a **sub-graph** (most likely Research, if it becomes a multi-step search loop), but we will not introduce a global supervisor-of-independent-agents architecture.

## Why

The teaching "capabilities" are phases of a single tutor's connected judgment flow, not independent specialists — splitting them into message-passing agents fragments the pedagogy and adds a delegation-LLM layer (more tokens, latency, failure modes) for no benefit. Critically, the supervisor pattern's headline benefit — context isolation / token control — is **already obtained** via the file-based state model (ADR-0003): each node reads only the files it needs instead of carrying the whole conversation. We get the main benefit without the supervisor machinery.

## Consequences

- Promoting a node to a sub-graph later is additive, not a reversal — this decision is cheap to revisit for individual nodes.
- Do not "fix" the architecture by adding a supervisor; the omission is deliberate.
