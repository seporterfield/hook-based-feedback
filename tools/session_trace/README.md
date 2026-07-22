# session_trace

Two deterministic tools for analyzing a Claude Code session log. No LLM, no
randomness. Same log in, same table out.

- **trace**: chronological, one row per conversation entry, showing how long each
  step took and what kind it was (inference, tool use by name, human wait, system
  wait).
- **report**: the same steps aggregated by category, descending by total time,
  with call counts.

## Usage

```bash
python3 session_trace.py trace  <session.jsonl | session-id> [--limit N] [--include-sidechain]
python3 session_trace.py report <session.jsonl | session-id> [--include-sidechain]
```

The positional argument is either a path to a `.jsonl` log or a bare session id,
which resolves to `~/.claude/projects/*/<id>.jsonl` (first match).

## Input format

Claude Code writes one JSON object per line to
`~/.claude/projects/<cwd-slug>/<session-id>.jsonl`. The tools read only these
fields, so they stay stable as the format grows:

- `type`: `user` or `assistant` (other types are ignored)
- `timestamp`: ISO 8601, used for all durations
- `message.content`: a string, or a list of `text` / `tool_use` / `tool_result` blocks
- `message.usage.output_tokens`: shown per inference row
- `isSidechain`: subagent turns, excluded unless `--include-sidechain`

## Method

Every wall-clock gap between two consecutive entries is attributed once, to the
category of the later entry. The categories partition the whole session, so the
report percentages sum to 100%.

- **inference**: a gap ending in an assistant message (model latency plus any
  PreToolUse hooks).
- **tool:NAME**: a gap ending in a user message that carries a `tool_result`. The
  tool name is resolved from the matching `tool_use` id.
- **human_wait**: a gap ending in a genuine human message.
- **system_wait**: a gap ending in an injected message (task notifications, hook
  feedback, slash-command output, interrupts), detected by structural markers.

## Caveats

- A backgrounded agent returns a quick launch acknowledgement (attributed to
  `tool:Agent`), and its completion arrives later as a task notification
  (`system_wait`). The long span while it runs is attributed to whatever the main
  loop was actually doing, which is correct.
- Parallel tool calls whose results batch into one user entry compress into a
  single row. The extra results are noted as `(+N batched)` and counted once.
- `human_wait` includes overnight or between-session gaps. It is real wall clock,
  not agent time. Read the report with that row set aside.

## Tests

```bash
python3 tests/test_session_trace.py
```

Deterministic, fixture-driven, stdlib only.
