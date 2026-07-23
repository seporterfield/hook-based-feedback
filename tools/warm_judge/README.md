# warm_judge

A daemon that keeps pre-warmed haiku judge sessions ready, so the Stop hook
gets its verdict from an already-primed session instead of cold-starting
one `claude` process per rule shard.

## Why

Every stop, the judge must read all your feedback rules plus the response.
Cold, that means spawning several `claude -p` processes (about 5s boot each)
and paying to process the full rule text every time. Measured on a 104-rule
setup, the cold path takes about 26s per stop.

Warm, the rules are sent once per session as a priming turn. The Anthropic
prompt cache keys on the prompt bytes, so every later session priming with
the same rules reads the cache instead of reprocessing (measured: 47,167
tokens written once, then read back on every refill). A judgment on a primed
session took 9 to 13s in testing, with occasional slower outliers when the
API throttles.

## How it works

1. `serve` boots one or more `claude -p --input-format stream-json` haiku
   sessions and sends each a priming turn containing all `feedback_*.md`
   rules. The session replies READY and waits.
2. The Stop hook sends the finished assistant response over a unix socket.
3. The daemon hands it to a primed session as one new turn and returns the
   verdict, violated rule filenames or NONE.
4. The used session is killed. A replacement is booted and primed in the
   background, off the critical path, so the next stop finds a warm slot.
5. Slots older than 15 minutes are recycled so rule edits get picked up.

Sessions are used for exactly one judgment. That keeps every verdict
independent, with no conversation history bleeding between judgments.

## Usage

Start the daemon (from the project the hooks run in, so it finds the same
memory dir):

```
python3 tools/warm_judge/warm_judge.py serve &
```

The Stop hook in `hooks/stop.py` checks for the daemon's socket on every
stop. Daemon running: warm path. Daemon absent or erroring: it falls back
to the original cold sharded path. No configuration needed.

Other commands:

```
python3 warm_judge.py status                      # pool state
python3 warm_judge.py judge --response "text"     # manual judgment
python3 warm_judge.py stop                        # shut down
```

`AGENT_MEMORY_DIR` or `CLAUDE_PROJECT_DIR` control which rules directory is
loaded, same resolution as the hooks.

## FAQ

**Is the pool per Claude session or per device?**

Per rules directory, shared across the device. Every Claude session on your
machine that uses the same rules directory talks to the same daemon and the
same pool. A different project gets a different socket, so it needs its own
daemon.

**Can any Claude session claim any slot?**

Yes. Slots belong to the daemon, not to any session. The first stop to ask
gets the primed slot. If two sessions stop at the same moment, the second
falls back to the cold path for that turn. Raise `--spares` if you run
several sessions in parallel.

**Can any slot judge any rule file?**

Yes. Every slot is primed with all the `feedback_*.md` files, so slots are
interchangeable. A new or edited rule reaches the pool when slots turn over,
after one use or at the 15 minute age limit, whichever comes first.

## Costs

Each priming turn is a real billed request. The first one writes the rule
text to the prompt cache, refills mostly read it back at cache-read rates.
Each recycled or refilled slot is one small request. Keep `--spares` at 1
unless stops arrive faster than one judgment finishes.
