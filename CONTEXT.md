# Self-Learning Agent

A standalone teaching agent (ported from the `teach` skill) that helps a learner acquire a skill or concept over multiple sessions, grounded in a personal mission. This glossary is the canonical language for the agent; all nodes, prompts, and artifacts must adhere to it.

## Language

**Mission**:
The concrete real-world reason the learner wants the topic; grounds every teaching decision. One per workspace.
_Avoid_: Goal, objective, purpose

**Lesson**:
A single, self-contained, **static** HTML file teaching one tightly-scoped thing tied to the mission. Ephemeral — rarely revisited after completion.
_Avoid_: Module, unit, page

**Reference Document**:
A compressed, reusable artifact (cheat sheet, algorithm, syntax, glossary) designed for quick repeat lookup. The durable counterpart to a Lesson — revisited often.
_Avoid_: Note, doc, handout

**Asset (Component)**:
A reusable building block shared across Lessons (stylesheet, quiz widget, simulator, diagram helper). Reuse is the default.
_Avoid_: Snippet, partial

**Learning Record**:
A decision-grade record of a non-obvious thing the learner now understands (or prior knowledge / corrected misconception), used to compute the zone of proximal development. Tracks what the learner has **learned** (evidence-grade) — as opposed to the **Coverage Ledger**, which tracks what has been **taught**. Not an activity log.
_Avoid_: Journal entry, log

**Coverage Ledger**:
The record of which Lessons have been delivered (one entry per committed Lesson: number, title, objective, summary), used to prevent re-teaching and to let the next Lesson build on prior ones. Written on every Lesson commit, independent of whether the learner is ever assessed. The **taught** counterpart to the **Learning Record** (which is about what was **learned**).
_Avoid_: Manifest, history, log

**Learner Notes**:
A rolling, low-barrier record of the learner's preferences, pace, recurring sticking points, open questions, and system/background context. The explicit substitute for the ambient conversational memory a hosted agent (e.g. `teach` inside Claude Code) would otherwise hold in context; fed into the generation nodes so they are not "amnesiac". Distinct from a Learning Record — Notes are soft, ongoing context, not evidence-grade decisions.
_Avoid_: Profile, memory, scratchpad

**Zone of Proximal Development (ZPD)**:
The band of difficulty where the learner is challenged "just enough" — the target for what to teach next.
_Avoid_: Skill level, difficulty

**Fluency strength**:
In-the-moment retrieval of knowledge. Can give an illusory sense of mastery.

**Storage strength**:
Long-term retention of knowledge — the real goal, built via desirable difficulty (retrieval practice, spacing, interleaving).

**Knowledge / Skills / Wisdom**:
The three learning targets — Knowledge from trusted resources, Skills from interactive practice, Wisdom from real-world community interaction. Difficulty is the enemy of Knowledge acquisition but the tool for Skill durability.

**Workspace Language**:
The single natural language a workspace's artifacts are written in, detected once from the learner's input when the Mission is established and persisted as a workspace fact. All model-generated content (Lessons, Mission, records, resource annotations) follows it; deterministic chrome labels are selected from a per-language table keyed by it (bounded set, English fallback). Not re-inferred per node.
_Avoid_: Locale, i18n

**Turn**:
A single learner message and the agent's complete response to it. A Turn flows through as many teaching capabilities as it needs (e.g. establishing the Mission, then gathering resources, then teaching), but pauses when it must ask the learner something, and delivers at most one Lesson before ending.
_Avoid_: Request, round, API call
