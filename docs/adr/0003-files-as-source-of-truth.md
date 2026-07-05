# Files as source of truth; checkpointer only for sessions

We separate three state layers: **(A) conversation/graph state** → LangGraph **checkpointer** (SQLite for MVP, Postgres for production); **(B) long-term learner memory** (`MISSION.md`, `learning-records/`, `GLOSSARY.md`, `RESOURCES.md`) and **(C) learning artifacts** (`lessons/*.html`, `reference/*`, `assets/*`) → **plain files**, namespaced per learner/topic as `workspaces/{user_id}/{topic_slug}/`. Files are the single source of truth for B and C; nodes read them into graph state at session start.

## Why

Avoids the dual-write inconsistency of mirroring memory into both files and a LangGraph store. The file model keeps Lessons portable/printable (ADR-0002), is isomorphic with the original `teach` design, and is the simplest thing for a multi-user MVP. A database / LangGraph store is a later tuning step, not an MVP requirement.

## Consequences

- No separate long-term `store` in the MVP — the Markdown files *are* the memory.
- Semantic retrieval over many learning records, if needed later, is added as a **derived read-only index** (e.g. vector store), never as the source of truth.
- Cloud move = swap the workspace directory for object storage; the logical model is unchanged.
