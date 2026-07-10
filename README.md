# hook-based-feedback

This repo is a starter kit for making a Claude Code agent enforce your feedback on itself.
It holds two things: the rules, one per file, and the hooks that check the agent against
them. It is for anyone running Claude Code who keeps giving the agent the same corrections
and wants them to stick across sessions.

A rule is one correction, written as a `feedback_<slug>.md` file: something you told the
agent to do or stop doing. Three ship by default:

- Validate system claims against docs or source, never from training data
- No status-quo open questions: research what is knowable, ask only about desired state
- Only write code comments when explicitly asked

## The three hooks

A hook is a script Claude Code runs on a lifecycle event. This kit uses three, all in
`hooks/`:

- `session_start.py` — at session start, clones your feedback repo into the agent's memory
  directory, a local per-project folder. The other two hooks read the rules from there.
- `edit.py` — after every edit, runs `check-edit-feedback.py`. That check asks a small model
  whether the edited code broke any rule marked `apply: code` in its frontmatter, the YAML
  block at the top of a rule file. If it did, the agent fixes it before moving on.
- `stop.py` — when the agent finishes a response, reads every rule and asks a small model
  whether the response broke any of them. If it did, the agent has to revise before the turn
  ends.

`edit.py` is an orchestrator: it runs the checks named in its `EDIT_CHECKS` list. Add a check
by dropping a script in `hooks/` and appending its filename to that list.

## Install

Copy the hook scripts into your project:

```
cp hooks/*.py your-project/.claude/hooks/
```

Wire them into `your-project/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session_start.py" }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write|NotebookEdit", "hooks": [{ "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/edit.py", "timeout": 100 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop.py", "timeout": 100 }] }
    ]
  }
}
```

Point `AGENT_FEEDBACK_REPO` at your fork so `session_start.py` can sync the rules:

```
export AGENT_FEEDBACK_REPO=https://<token>@github.com/<you>/hook-based-feedback.git
```

The hooks shell out to the `claude` CLI for their small-model checks, so it must be on your
PATH.

## Add a rule

Create a `feedback_<slug>.md` file with frontmatter and the rule text:

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

Add `apply: code` only if the rule should be enforced on code edits by `edit.py`. Rules
without it are still checked at the end of the turn by `stop.py`. Commit and push to your
fork:

```
git add feedback_<slug>.md
git commit -m "Add <slug> rule"
git push
```

The rule is live the next session.
