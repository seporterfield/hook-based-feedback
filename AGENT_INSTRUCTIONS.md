# Agent instructions

For a Claude Code agent setting this feedback harness up in a project, or adding to it. Do
the section that applies.

## Wire the hooks into a project

Copy the hook scripts into the project's hook directory:

```
cp hooks/*.py .claude/hooks/
```

Merge these entries into `.claude/settings.json`, keeping any hooks already there:

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

Set `AGENT_FEEDBACK_REPO` so `session_start.py` syncs the rules each session:

```
export AGENT_FEEDBACK_REPO=https://<token>@github.com/<you>/hook-based-feedback.git
```

Confirm the `claude` CLI is on PATH. The hooks shell out to it for their small-model checks.

## Add a rule

Create a `feedback_<slug>.md` file at the repo root with frontmatter and the rule text:

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
without it are checked at the end of the turn by `stop.py`. Then commit and push:

```
git add feedback_<slug>.md
git commit -m "Add <slug> rule"
git push
```

The rule is live the next session.

## Enable warm judging (optional)

Start the warm judge daemon so Stop-hook verdicts come from pre-primed haiku
sessions instead of cold spawns:

```
python3 tools/warm_judge/warm_judge.py serve &
```

Or set `WARM_JUDGE=1` and `session_start.py` starts it for you each session,
using the copy synced into the memory dir. Each primed session is a real
billed request, so this stays opt-in.

`stop.py` uses it automatically when the daemon is up and falls back to cold
spawns when it is not. Details in [tools/warm_judge](tools/warm_judge/README.md).

## Add a check

`edit.py` runs the scripts named in its `EDIT_CHECKS` list. To add one, drop a script in
`hooks/` and append its filename to that list.
