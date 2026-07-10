# hook-based-feedback

Starter feedback repo for the `hook-based` harness branch of metadev. It holds the
per-user rules the agent enforces on itself, plus the hooks the branch's orchestrators
fan in.

The harness works like this: the branch ships five per-event hook orchestrators. On Stop,
a built-in judge reads every `feedback_*.md` here and asks a haiku model whether the last
response violated any of them. The `hooks/manifest.json` wires additional per-event checks,
resolved against this directory.

## Contents

- `feedback_*.md` — the rules. Three ship by default:
  - Validate system claims against docs or source (no answering from training data)
  - No status-quo open questions (research what is knowable, only ask about desired state)
  - Only write code comments when explicitly asked
- `hooks/manifest.json` — wires `check-edit-feedback.py` on PostToolUse so rules marked
  `apply: code` in their frontmatter are caught at edit time, not just at end of turn.
- `hooks/check-edit-feedback.py` — the edit-time code-style judge. It discovers which rules
  apply to code by the `apply: code` frontmatter marker, and derives the memory dir from its
  own location, so it works regardless of checkout path.

## Use it

This repo is the default `AGENT_FEEDBACK_REPO` for the `hook-based` branch. To use your own,
fork it and set the env var to your fork:

```
export AGENT_FEEDBACK_REPO=https://<token>@github.com/<you>/hook-based-feedback.git
```

Add a rule by writing a new `feedback_<slug>.md` with frontmatter (`name`, `description`,
`type: feedback`, and `apply: code` if it should be enforced on code edits), then commit and
push. The branch syncs this repo into the derived memory dir on session start.
