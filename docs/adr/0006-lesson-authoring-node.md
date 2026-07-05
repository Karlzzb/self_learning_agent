# Lesson authoring: design-system + components, with a validate/critique sub-graph

The Lesson authoring capability is a **sub-graph**, not a single LLM call. Lessons are composed from a **shared design system (one CSS token sheet) + a reusable component library in `assets/`** (option c) — the node reads `assets/` first and builds from existing components, adding new reusable ones only when needed. The sub-graph runs: **1) draft (strong model composes from components) → 2) mechanical validation → 3) LLM self-critique against a pedagogy rubric → revise until it passes**.

## Why

One-shot HTML generation drifts in style, breaks links, and gambles quality — unacceptable for a product whose deliverable *is* the lesson. Quality is guaranteed by **architecture, not by hoping the model gets it right once** (aligns with the project principle: never degrade design for model limits). Step 2 is **deterministic code, not an LLM**: HTML parses, internal/asset links resolve, every citation exists in `RESOURCES.md`. Step 3 is an LLM scored against `SKILL.md`'s hard constraints (short enough for working memory, one tangible win, tied to mission + ZPD, every claim cited, a primary-source recommendation, equal-length quiz options, "ask your teacher" reminder).

## Consequences

- The shared stylesheet is the first component every workspace earns; lessons look like one course, not a pile of one-offs.
- MVP mechanical checks are static (parse + link/asset existence + citation cross-ref). Headless-browser render checks (e.g. Playwright, catching JS errors) are a post-MVP enhancement.
- The quality gate is an **MVP requirement**, not deferred tuning.
