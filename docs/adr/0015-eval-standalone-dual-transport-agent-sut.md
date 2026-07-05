# Eval as a standalone dual-transport suite with an agent-behaviour SUT

> **Status: Abandoned (2026-07-03).** The standalone `eval/` suite this ADR builds has been removed from the repo. Kept as a historical decision record only; do not rebuild against it without a fresh decision.

We complete `eval/` into a **standalone, installable** acceptance/regression suite that drives the **live** agent end-to-end over a **swappable Eval Transport** (in-process function call ↔ deployed HTTP API), adds a **second SUT** for agent behaviour (P1–P7) projected onto the **same evaluation quadrants** as the lesson rubric (ADR-0014), and exposes a **model-free deterministic gate** that QA can run against a deployed service without the source tree.

## Context

ADR-0014 built `eval/` as a projection of `RUBRIC.md`, but only for the **lesson artifact** SUT, driven **in-process** with live models, and it explicitly deferred the **P1–P7 agent-behaviour** SUT to roadmap.
Two gaps remained: (1) the suite is not a complete agent test — it never exercises turn/node behaviour against a live model (the hermetic `tests/*_seam.py` cover control-flow **wiring with fake models**, not live behavioural quality); (2) the suite cannot run independently of the project — both `providers/lesson_provider.py` and `assertions.py` import `src/` directly, so QA cannot point it at a deployed service.

## Decision

- **Eval Transport seam.** The eval provider reaches the agent through an interchangeable transport: **in-process** (`runner.invoke_turn`, current) or **HTTP** (`POST /chat`, then `GET /artifacts/content` to read produced artifacts). Same scenarios, same assertions; only the reach differs. The transports are **not** pure duplicates — `api.py`'s `/chat` performs the `spawn_topic` auto-handoff that in-process does not — so running both has real contract value.
- **Gold Scenario = scripted multi-turn conversation.** A fresh workspace necessarily interrupts for the mission interview and then the first-lesson menu (#016), and **HTTP cannot pre-seed a workspace** (the API has no write-mission endpoint). So a scenario is a **set of response policies keyed by the kind of question the agent asks** (mirroring the hermetic `default_responder`, robust to real-model nondeterminism at interrupt points) plus a **declared expected terminal state**. Lesson-quality scenarios become the subset that ends in a delivered lesson.
- **Unified scenario corpus.** One schema carries both SUTs: each scenario declares its terminal state and which quadrant assertions apply. The provider returns the full transcript plus any artifacts; assertions take what they need.
- **P1–P7 projected onto the same quadrants.** Structurally observable behaviour (mission-unclear → `awaiting_input`; change → `MISSION.md` updated + learning record appended; search-empty → no `RESOURCES.md`, no lesson, honest reply; reference produced; glossary adhered) is a **model-free behaviour gate**; judgement behaviour (high-reputation community, evidence-grade records, opinionated glossary) goes to the judge — same two-axis logic as L1–L17.
- **Standalone, installable eval depending on the main package.** `eval/` becomes its own sub-project (own `pyproject`) declaring dependencies on `self-learning-agent` + promptfoo. QA installs it and points the transport at a deployed service. The **deterministic gate is model-free** (pure `validators`, standard-library only), so QA's acceptance run needs no model key and no source checkout — only the installed package. Reading artifacts for the gate goes through a workspace-accessor with two impls (filesystem in-process / `GET /artifacts` over HTTP).
- **Run-scoped isolation against a deployed service.** Each run uses a unique `user_id` (e.g. `eval-<runid>`) and per-scenario unique topics, and deletes each workspace via `DELETE /workspace` on teardown — namespaced away from real users, no residue.

## Considered options

- **Vendor `validators` into `eval/`.** Rejected: forks the single source of truth that ADR-0014 exists to protect. `validators` is a pure, zero-third-party-dependency module, so installing it via the package is cheap.
- **Add a service-side `/evaluate` scoring endpoint** so the QA suite is a zero-Python HTTP client. Rejected: pushes the scoring surface into the production API, in tension with ADR-0004 ("the agent never manages evaluation").
- **Keep single-shot scenarios + pre-seed the workspace.** Rejected: pre-seeding is impossible over HTTP without a new write endpoint, which would fork the two transports; scripted conversations keep them behaviourally identical and test the real end-to-end path.

## Consequences

- The deterministic gate is now **doubly useful**: the same model-free checks are the Lesson authoring sub-graph's quality gate (ADR-0006) **and** QA's deployment-acceptance gate — never copied, only imported.
- Future readers seeing `eval/` import an installed package and carry two transports + multi-turn response policies should not "simplify" it back to an in-process single-shot import: that would refork the source of truth and drop the live-agent / deployed-service coverage this decision exists to add.
- `docs/validation-rubric.md`, `eval/validation-cases.yaml`, and the scenario corpus must now also track the P1–P7 → quadrant projection, under the same sync discipline ADR-0014 established for L1–L17.
