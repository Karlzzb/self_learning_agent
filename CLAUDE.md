# Self-Learning Agent

Standalone teaching agent ported from the `teach` Claude Code skill onto LangGraph + Qwen.

**New here? Read `OVERVIEW.md` first** — it is the exploration entry point (current status + doc map + what to skip).
Then see `PRD.md` for the product spec, `RUBRIC.md` for the authoritative lesson/agent quality rubric,
`CONTEXT.md` for the domain glossary, and `docs/adr/` for architectural decisions.

## Agent skills

### Issue tracker

Issues live as local markdown under `.scratch/issues/<NNN>-<slug>.md` (no git remote). See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical five-role vocabulary, applied via a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context layout (root `CONTEXT.md` glossary today; `CONTEXT-MAP.md` to be added as contexts split). See `docs/agents/domain.md`.
