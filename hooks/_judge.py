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
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from _harness import memory_dir

COLD_TIMEOUT_S = 25
WARM_TIMEOUT_S = 75
SHARD_SIZE = 12
MAX_WORKERS = 8

FLAGGED_PATTERN = re.compile(r"feedback_[a-z0-9_]+(?:\.md)?")
HOOK_ENV = {"CLAUDE_HOOK_NO_CHECK": "1", "CLAUDE_JUDGE_RUNNING": "1"}

PromptBuilder = Callable[[str], str]


def run_haiku(prompt: str, timeout: float = COLD_TIMEOUT_S) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **HOOK_ENV},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def rules_block(memories: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"=== {name} ===\n{body}" for name, body in memories)


def flagged_names(verdicts: list[str]) -> list[str]:
    names: list[str] = []
    for verdict in verdicts:
        if not verdict:
            continue
        if verdict.upper().splitlines()[0].strip() == "NONE":
            continue
        for name in FLAGGED_PATTERN.findall(verdict):
            names.append(name if name.endswith(".md") else f"{name}.md")
    return list(dict.fromkeys(names))


def warm_socket_path() -> Path:
    digest = hashlib.md5(str(memory_dir()).encode()).hexdigest()[:8]
    return Path(f"/tmp/warm-judge-{os.getuid()}-{digest}.sock")


def ask_warm_pool(response: str) -> str | None:
    path = warm_socket_path()
    if not path.exists():
        return None
    try:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(WARM_TIMEOUT_S)
        connection.connect(str(path))
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
    return reply.get("verdict")


def judge_sharded(
    memories: list[tuple[str, str]],
    build_prompt: PromptBuilder,
    timeout: float = COLD_TIMEOUT_S,
) -> list[str]:
    if not memories:
        return []
    shards = [
        memories[start : start + SHARD_SIZE]
        for start in range(0, len(memories), SHARD_SIZE)
    ]
    with ThreadPoolExecutor(max_workers=min(len(shards), MAX_WORKERS)) as executor:
        verdicts = list(
            executor.map(
                lambda pile: run_haiku(build_prompt(rules_block(pile)), timeout),
                shards,
            )
        )
    return flagged_names(verdicts)


def judge_response(
    response: str,
    memories: list[tuple[str, str]],
    build_prompt: PromptBuilder,
) -> list[str]:
    warm_verdict = ask_warm_pool(response)
    if warm_verdict is not None:
        return flagged_names([warm_verdict])
    return judge_sharded(memories, build_prompt)
