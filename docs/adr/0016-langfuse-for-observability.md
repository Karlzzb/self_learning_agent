# Langfuse for observability

**Status: Accepted (2026-07-03). Supersedes [ADR-0008](0008-langsmith-for-dev-observability.md).**

We trace/observe the agent with **self-hosted Langfuse** instead of hosted LangSmith.
The agent is a black box of nodes each calling an LLM plus a search and a revise loop; tracing lets us replay every step (which node ran, the prompt, the model, tokens, latency, output) — the prerequisite for the "continuously tunable" goal.
ADR-0008 already anticipated this swap ("swapping LangSmith ↔ self-hosted Langfuse later is low-cost if ever desired"); this ADR executes it.

## Why

- **Self-hosting.** We run our own Langfuse instance, keeping traces on infrastructure we control. There is still no data-residency *requirement*, but self-hosting removes reliance on a third-party SaaS and its account/quota.
- **Same tunability payoff.** Langfuse gives the same per-node replay (prompt / model / tokens / latency / output) that made tracing worth wiring in the first place.

## How it wires in (the delta from LangSmith)

This is the one place the swap is *not* free. LangSmith was purely env-var driven — LangChain auto-detects `LANGSMITH_*` and needs zero code. **Langfuse traces through the LangChain callback mechanism**: a `CallbackHandler` must be passed via `config={"callbacks": [...]}` on each `graph.invoke`.

To keep that wiring out of the business nodes, it is collapsed into a single seam — `observability.get_callbacks()` — mirroring how search hides behind `search()` and models behind `get_model()`:

- The only graph-driving kernel, `runner.invoke_turn`, calls `get_callbacks()` and attaches the result to the invoke config. Business nodes are untouched.
- `get_callbacks()` returns `[]` when `LANGFUSE_TRACING` is off — and in that case does **not** import `langfuse` at all, so environments without the dependency (e.g. the hermetic test suite) and disabled deployments are unaffected. An empty callbacks list is a harmless no-op, so the driver needs no branching.
- Keys and host are injected via `.env` (`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`); `CallbackHandler()` reads them from the environment. The agent never handles plaintext secrets or self-manages the account (consistent with ADR-0004).

## Consequences

- Observability sits behind the `observability` seam plus standard env config. Swapping backend again (or back) is a change to that one module; the graph and nodes do not move.
- Tracing failure is non-fatal: a missing `langfuse` dependency or a handler init error degrades to "tracing off + one warning", never taking down the teaching flow (ADR-0009 posture — observability is a side-channel).
