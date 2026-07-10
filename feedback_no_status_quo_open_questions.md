---
name: No status-quo open questions
description: "Open questions must be about desired state only; status-quo questions answerable from code, history, configs, or external systems must be researched, not listed as open"
type: feedback
---

Never list a status-quo question as an "open question" in a plan, spec, or PR description. Status-quo means: anything answerable by reading code, git history, configs, S3, CloudWatch, or external systems I already have access to. If it's empirical, it's not open.

**Open questions are only about desired state** — what the user wants the system to do, what the user prefers between two valid paths, what the user considers in scope. Anything else, I research before writing.

**Why:** A plan with unanswered status-quo questions is a half-finished plan. The user has to do my work for me, and they correctly read it as the agent failing to commit to the investigation. The "open question" frame is also misleading: it presents researchable facts as ambiguous and shifts decision cost to the user.

**How to apply:**
- Before listing any question as "open", ask: is this about *what the user wants* or *what currently is*?
- "What currently is" — go grep, fetch, read. Answer it in the plan with citations.
- "What the user wants" — that's a real open question. Keep it. Label it `Decision needed:` not "open question".
- If status-quo research takes too long or requires access I don't have, say so explicitly: "I checked X, Y, Z and didn't find an answer, here's what I'd need access to" — not "open question".
- When delegating to a Plan or Explore agent, pre-load the agent with the status-quo questions so the answers come back with the investigation, not after.
