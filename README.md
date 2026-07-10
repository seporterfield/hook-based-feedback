# hook-based-feedback

This repo holds the feedback rules a Claude Code agent enforces on itself. It serves anyone
running a hook-based Claude Code harness. A harness is a set of hooks that fire on each
prompt, edit, and response. Its purpose is to keep your corrections working from one session to the next,
instead of re-explaining them each time. Each file is one rule, named `feedback_<slug>.md`:
something you told the agent to do or stop doing.

## How the agent uses these rules

At session start, the agent clones this repo into its memory directory, a local per-project
folder. Two of the harness hooks then do the enforcing.

The first is an end-of-turn check. When the agent finishes a response, the check reads every
`feedback_*.md` file in the memory directory. It then asks a small model whether the
response broke any rule. If the response breaks a rule, the agent has to revise before the
turn ends.

The second is an edit-time check, for rules about code the agent writes rather than its
prose. You mark those rules `apply: code` in their frontmatter, the YAML block at the top of
each file. The check runs right after each edit and names any code rule the edit breaks, so
the agent fixes the violation as the code is written.

## What's in the repo

- `feedback_*.md` — the rules. Three ship by default:
  - Validate system claims against docs or source, never from training data
  - No status-quo open questions: research what is knowable, ask only about desired state
  - Only write code comments when explicitly asked
- `hooks/check-edit-feedback.py` — the edit-time check. It finds code rules by their
  `apply: code` marker and derives the memory directory from its own location, so it runs at
  any checkout path
- `hooks/manifest.json` — tells the harness to run the edit-time check after each edit

The end-of-turn check ships with the harness itself, not this repo.

## Use it

Requires git and a Claude Code harness that reads `AGENT_FEEDBACK_REPO`.

Point your agent's `AGENT_FEEDBACK_REPO` at this repo, or fork it and use your fork:

```
export AGENT_FEEDBACK_REPO=https://<token>@github.com/<you>/hook-based-feedback.git
```

To add a rule, create a `feedback_<slug>.md` file with frontmatter and the rule text:

```markdown
---
name: Prefer early returns over nested conditionals
description: Use guard clauses instead of nesting the body in if/else
type: feedback
apply: code
---

Write guard clauses that return early instead of wrapping the body in nested
if/else. Keep the happy path at the lowest indentation level.
```

Add `apply: code` only if the rule should be enforced on code edits. Then commit and push it
to your fork:

```
git add feedback_<slug>.md
git commit -m "Add <slug> rule"
git push
```

The rule is live the next session.
