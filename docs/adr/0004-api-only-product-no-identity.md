# Product surface is an API; the agent never owns identity or billing

The productized form of this agent is an **API consumed by other systems**, not an end-user web app. The agent does **not** manage user accounts, authentication, or billing — those are the calling system's responsibility. The MVP front-end is a **CLI** driving the same graph; productization wraps that identical graph in an HTTP API.

## Why

User stated that even if successful, the agent stays an API for other systems and will never own accounts/billing. This resolves the earlier A(product)/C(learning) tension: there is no frontend/auth/billing to build, so "product" = wrapping a proven graph in an API — a low-risk increment over the CLI engine.

## Consequences

- **Multi-tenancy by externally-supplied id only.** The caller passes a `user_id`/`topic`; the agent namespaces `workspaces/{user_id}/{topic_slug}/` and `thread_id` from it. The agent performs **no** auth — it trusts the caller's identity.
- Learning artifacts (HTML lessons) are returned/served to the calling system, which renders them in its own UI. `open in browser` is a CLI-only convenience, absent from the API path.
- CLI and API are two thin drivers over **one** graph; no core architecture differs between them.
