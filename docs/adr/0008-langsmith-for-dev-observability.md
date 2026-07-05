# LangSmith for observability

> **Status: Superseded by [ADR-0016](0016-langfuse-for-observability.md) (2026-07-03).**
> The observability backend moved from hosted LangSmith to self-hosted **Langfuse**.
> The reasoning below still records *why* observability sits behind a swappable tracing seam — the choice this ADR anticipated in "Consequences" — but the concrete backend is no longer LangSmith.

We use **LangSmith** for tracing/observability. The agent is a black box of 7 nodes each calling an LLM plus a search and a revise loop; tracing lets us replay every step (which node ran, the prompt, the model, tokens, latency, output) — the prerequisite for the "continuously tunable" goal.

## Why

LangSmith has the easiest integration (env vars) and the best trace UI, directly serving tunability. There is **no data-residency requirement** for this project (an earlier assumption to the contrary was wrong) and data/queries are global, so hosted SaaS tracing is fine in both development and production.

## Consequences

- Observability sits behind standard LangChain tracing config, so swapping LangSmith ↔ self-hosted Langfuse later is low-cost if ever desired (e.g. for cost reasons, not residency).
