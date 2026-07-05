# In-lesson feedback: client-side HTML + conversational assessment (MVP)

The in-lesson micro feedback loop (quizzes/practice) is handled by **(i) client-side JS inside the static HTML lesson** for closed-form practice, plus **(ii) conversational assessment by the agent** for open-ended / wisdom-level checks that update learning records. We deliberately defer **(iii)** the hybrid where lesson HTML calls back to a live agent API.

## Why

(iii) is where productization complexity concentrates — it turns Lessons from portable static files into live app surfaces requiring a permanently-running agent service, an API, and auth. Deferring it is an MVP scope decision, not a concession to model limits. (i)+(ii) keeps Lessons portable/printable/revisitable while keeping the adaptive loop (assessment → learning records → ZPD) inside the agent via conversation.

## Consequences

- Lessons remain **static, self-contained HTML files**, preserving the Lesson vs Reference Document distinction.
- Quiz results do **not** auto-flow into ZPD in the MVP; the agent learns how the user did by talking to them. Auto-flow is a post-MVP enhancement that depends on (iii).
