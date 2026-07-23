#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import guard_active, memory_dir, read_stdin

TIMEOUT_S = 25
MAX_RESPONSE_CHARS = 6000
MAX_MEMORY_BODY_CHARS = 1200
SHARD_SIZE = 12
MAX_WORKERS = 8
WARM_JUDGE_TIMEOUT_S = 75


def read_last_assistant_text(transcript_path: Path) -> str:
    last = ""
    with transcript_path.open() as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = entry.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            text_chunks = [
                chunk.get("text", "")
                for chunk in content
                if isinstance(chunk, dict) and chunk.get("type") == "text"
            ]
            if text_chunks:
                last = "\n".join(text_chunks)
    return last


def load_feedback_memories() -> list[tuple[str, str]]:
    directory = memory_dir()
    if not directory.is_dir():
        return []
    memories = []
    for path in sorted(directory.glob("feedback_*.md")):
        try:
            body = path.read_text().replace("\x00", "")
        except OSError:
            continue
        memories.append((path.name, body[:MAX_MEMORY_BODY_CHARS]))
    return memories


def ask_haiku(response: str, memories: list[tuple[str, str]]) -> str:
    memory_block = "\n\n".join(
        f"=== {name} ===\n{body}" for name, body in memories
    )
    prompt = f"""You are a strict reviewer. Below is an assistant's response to a user, followed by a set of feedback rules the assistant has previously been given by this user.

Identify which (if any) of the feedback rules this response clearly violates.

Be conservative. Only flag CLEAR violations. If you have to argue for the violation, don't flag it.

Output format: filenames of violated rules, one per line, with no prefix and no commentary. If no rules are clearly violated, output exactly:
NONE

===== ASSISTANT RESPONSE =====
{response[:MAX_RESPONSE_CHARS]}

===== FEEDBACK RULES =====
{memory_block}

===== VIOLATED FILENAMES (one per line, or NONE) ====="""

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env={**os.environ, "CLAUDE_HOOK_NO_CHECK": "1"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "NONE"
    return result.stdout.strip()


def ask_warm_judge(response: str) -> str | None:
    digest = hashlib.md5(str(memory_dir()).encode()).hexdigest()[:8]
    path = f"/tmp/warm-judge-{os.getuid()}-{digest}.sock"
    if not os.path.exists(path):
        return None
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(WARM_JUDGE_TIMEOUT_S)
        connection.connect(path)
        connection.sendall(
            json.dumps({"command": "judge", "response": response}).encode() + b"\n"
        )
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
        connection.close()
        reply = json.loads(b"".join(chunks))
    except (OSError, ValueError):
        return None
    if "verdict" not in reply:
        return None
    return reply["verdict"]


def check_feedback_violations(payload: dict) -> int:
    transcript = payload.get("transcript_path", "")
    if not transcript or not Path(transcript).is_file():
        return 0

    response = read_last_assistant_text(Path(transcript))
    if not response.strip():
        return 0

    memories = load_feedback_memories()
    if not memories:
        return 0

    warm_verdict = ask_warm_judge(response)
    if warm_verdict is not None:
        verdicts = [warm_verdict]
    else:
        shards = [
            memories[i : i + SHARD_SIZE] for i in range(0, len(memories), SHARD_SIZE)
        ]
        with ThreadPoolExecutor(max_workers=min(len(shards), MAX_WORKERS)) as executor:
            verdicts = list(
                executor.map(lambda shard: ask_haiku(response, shard), shards)
            )

    flagged: list[str] = []
    for verdict in verdicts:
        if not verdict or verdict.upper().splitlines()[0].strip() == "NONE":
            continue
        for name in re.findall(r"feedback_[a-z0-9_]+(?:\.md)?", verdict):
            flagged.append(name if name.endswith(".md") else f"{name}.md")
    flagged = list(dict.fromkeys(flagged))
    if not flagged:
        return 0

    print(
        "[feedback-check] Your last response appears to violate the following"
        " feedback memory rule(s):\n"
        + "\n".join(f"  - {name}" for name in flagged)
        + "\n\n"
        "Re-read the rule(s) at "
        f"{memory_dir()}\n"
        "and revise the response.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if guard_active():
        return 0
    _, payload = read_stdin()
    return check_feedback_violations(payload)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
