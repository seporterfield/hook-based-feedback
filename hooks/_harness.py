from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def memory_dir() -> Path:
    override = os.environ.get("AGENT_MEMORY_DIR")
    if override:
        return Path(override).expanduser()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    mangled = str(Path(project).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / mangled / "memory"


def guard_active() -> bool:
    return (
        os.environ.get("CLAUDE_HOOK_NO_CHECK") == "1"
        or os.environ.get("CLAUDE_JUDGE_RUNNING") == "1"
    )


def read_stdin() -> tuple[bytes, dict]:
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return raw, payload


def sync_feedback_repo() -> None:
    marker = Path("/tmp/agent-feedback-synced")
    if marker.exists():
        return
    repo = os.environ.get("AGENT_FEEDBACK_REPO")
    memory = memory_dir()
    try:
        if (memory / ".git").is_dir():
            subprocess.run(
                ["git", "-C", str(memory), "pull", "--ff-only"],
                capture_output=True,
                timeout=60,
            )
        elif repo:
            memory.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", repo, str(memory)],
                capture_output=True,
                timeout=120,
            )
        else:
            print(
                "AGENT_FEEDBACK_REPO is unset and the memory dir is not a git repo,"
                " so the checks find no rules. Set AGENT_FEEDBACK_REPO to your"
                " feedback repo.",
                file=sys.stderr,
            )
    except (OSError, subprocess.TimeoutExpired):
        pass
    if (memory / ".git").is_dir():
        try:
            marker.touch()
        except OSError:
            pass
