# hook-based-feedback

This repo is a starter kit for making a Claude Code agent enforce your feedback on itself.
It is for anyone running Claude Code who keeps giving the agent the same corrections
and wants them to stick across sessions.

Feedback is a correction written as a `feedback_<slug>.md` file.

```markdown
---
name: Claude, you made a mistake
description: Description of mistake
type: feedback
---

Don't make this mistake again: ....
```

- Validate system claims against docs or source, never from training data
- No status-quo open questions: research what is knowable, ask only about desired state
- Only write code comments when explicitly asked

## Hooks

A hook is a script Claude Code runs on a lifecycle event.
This quickstart uses three but [you can add more](link to anthropic docs enumerating hooks)
`hooks/`:

- `session_start.py` - setup
- `edit.py` - runs after every edit
- `stop.py` - runs when agent finishes responding

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
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session_start.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/edit.py",
            "timeout": 100
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop.py",
            "timeout": 100
          }
        ]
      }
    ]
  }
}
```

Point the `AGENT_FEEDBACK_REPO` env var at your fork so `session_start.py` can sync the rules:

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
