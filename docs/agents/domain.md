# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase. This repo is configured as **multi-context**.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`CONTEXT.md`** at the repo root — today this holds the canonical glossary for the whole agent (Mission, Lesson, Reference Document, Asset, Learning Record, ZPD, Fluency/Storage strength, Knowledge/Skills/Wisdom). It remains authoritative until contexts are split out under a `CONTEXT-MAP.md`.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in (0001–0011 cover the graph shape, feedback placement, files-as-source-of-truth, API-only product, single-graph/no-supervisor, lesson authoring, minimal tools, observability, failure posture, turn-cascade edges, first-lesson menu + new-topic handoff). In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

This repo is multi-context (presence of, or intent toward, `CONTEXT-MAP.md` at the root):

```
/
├── CONTEXT-MAP.md                     ← add when contexts split; points at per-context CONTEXT.md
├── CONTEXT.md                         ← current canonical glossary (whole agent)
├── docs/adr/                          ← system-wide decisions (0001–0011)
└── src/
    ├── <context-a>/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── <context-b>/
        ├── CONTEXT.md
        └── docs/adr/
```

When the codebase grows into separate contexts (e.g. teaching graph vs. HTTP API surface vs. CLI driver), add `CONTEXT-MAP.md` at the root and move per-context glossaries under `src/<context>/CONTEXT.md`.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids (e.g. use **Mission**, not goal/objective/purpose; **Lesson**, not module/unit/page; **Learning Record**, not journal/log).

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0003 (files as the single source of truth) — but worth reopening because…_
