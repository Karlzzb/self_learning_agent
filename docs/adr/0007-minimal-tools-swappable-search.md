# Minimal tool surface; one web search behind a swappable interface

The agent's external tool surface is deliberately minimal, replicating what the original `teach` skill actually used inside Claude Code: **one web search tool** (plus a simple page-fetch when full-text vetting is needed). Search sits behind an internal `search(query) -> candidates` interface so the provider is a one-line swap. The MVP provider is **Bailian/DashScope's built-in `enable_search`** — no new vendor or API key, billed within the model platform already in use, reachable from the deployment environment, and covers the global web. This mirrors how Claude Code's WebSearch was a paid hosted capability bundled into the service.

Note: the only hard constraint on the search provider is **reachability** (Tavily is unreachable from China — a network/accessibility issue, **not** a data-residency requirement; there is no data-residency requirement, and queries are global). Provider choice is otherwise about quality and cost.

## Why

`teach` worked with a single discrete web-search tool and never used MCP, RAG, or a reranker — confirmed by the user's own experience. Adding a separate paid search vendor (e.g. Tavily — also not usable in China; or Bocha — extra vendor/key) is unjustified for MVP. The durable decision is the **swappable interface**, not the provider: business nodes never change when search is later swapped to SearXNG (self-hosted, free), Bocha (higher-quality candidates), or DuckDuckGo.

## Consequences

- **No MCP** (`langchain-mcp-adapters`), **no RAG/vector store**, **no reranker** in the MVP — deliberate deviations from early LangGraph reference recommendations. Do not "fix" by adding them.
- File read/write and "open lesson in browser" are plain code, **not** LLM tools.
- `assigned_site_list` / `enable_citation` (Bailian search options) are noted as a future "trusted-source allowlist + auto-citation" tuning knob, not part of MVP.
- If curation quality with `enable_search` proves weak (it synthesizes rather than returning raw candidates), swap the interface impl to Bocha or self-hosted SearXNG.
