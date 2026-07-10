# hook-based-feedback

This repo holds the feedback rules a Claude Code agent enforces on itself. Each file is
one rule: something you told the agent to do or stop doing. You fork the repo, point your
agent at your fork, and add a rule every time you correct the agent.

## How the agent uses these rules

When the agent finishes a response, a check reads every `feedback_*.md` here and asks a
small model whether the response broke any rule. If one broke, the agent has to revise
before the turn ends. This check is always on and needs nothing beyond the rule files.

Some rules govern code the agent writes, not its prose. Those carry `apply: code` in their
frontmatter. `hooks/manifest.json` runs `hooks/check-edit-feedback.py` right after each
edit, so a code rule is caught as the code is written, not only at the end of the turn.

## What's in the repo

- `feedback_*.md` — the rules. Three ship by default:
  - Validate system claims against docs or source, never from training data
  - No status-quo open questions: research what is knowable, ask only about desired state
  - Only write code comments when explicitly asked
- `hooks/manifest.json` — wires the edit-time check described above
- `hooks/check-edit-feedback.py` — the edit-time judge. It finds code rules by their
  `apply: code` marker and derives its memory dir from its own location, so it works at any
  checkout path

## Use it

Point your agent's `AGENT_FEEDBACK_REPO` at this repo, or fork it and use your fork:

```
export AGENT_FEEDBACK_REPO=https://<token>@github.com/<you>/hook-based-feedback.git
```

Add a rule by writing a new `feedback_<slug>.md` with frontmatter (`name`, `description`,
`type: feedback`, plus `apply: code` if it should be enforced on code edits), then commit
and push. The agent syncs this repo into its memory dir at session start.
