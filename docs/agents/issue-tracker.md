# Issue tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `.scratch/`. This repo has no git remote; work is tracked locally.

## Conventions

- This repo is a single feature (the standalone port of the `teach` skill), so issues live flat:
  `.scratch/issues/<NNN>-<slug>.md`, numbered from `001`.
- The PRD lives at the repo root (`PRD.md`); the authoritative rubric at `RUBRIC.md`.
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings). Issues created by `to-issues` also carry a `**Type:** HITL/AFK` line.
- Each issue records its `## Blocked by` dependencies by issue number (e.g. `- #002`).
- Comments and conversation history append to the bottom of the file under a `## Comments` heading.

## When a skill says "publish to the issue tracker"

Create a new file at `.scratch/issues/<NNN>-<slug>.md` (creating the directory if needed), numbered as the next free `NNN`. Publish in dependency order so `## Blocked by` can reference real issue numbers.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly (e.g. `#007` → `.scratch/issues/007-*.md`).

## If this repo later gains a remote

To migrate to GitHub/GitLab, re-run `/setup-matt-pocock-skills` to switch the tracker, then import these markdown files as issues.
