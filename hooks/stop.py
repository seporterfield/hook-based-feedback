#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import guard_active, memory_dir, read_stdin
from _judge import judge_response

MAX_RESPONSE_CHARS = 6000
MAX_MEMORY_BODY_CHARS = 1200

RESPONSE_PROMPT = """You are a strict reviewer. Below is an assistant's response to a user, followed by a set of feedback rules the assistant has previously been given by this user.

Identify which (if any) of the feedback rules this response clearly violates.

Be conservative. Only flag CLEAR violations. If you have to argue for the violation, don't flag it.

Output format: filenames of violated rules, one per line, with no prefix and no commentary. If no rules are clearly violated, output exactly:
NONE

===== ASSISTANT RESPONSE =====
{response}

===== FEEDBACK RULES =====
{rules}

===== VIOLATED FILENAMES (one per line, or NONE) ====="""


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

    flagged = judge_response(
        response,
        memories,
        lambda rules: RESPONSE_PROMPT.format(
            response=response[:MAX_RESPONSE_CHARS], rules=rules
        ),
    )
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
