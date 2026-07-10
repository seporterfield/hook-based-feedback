#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent
TIMEOUT_S = 120
MAX_CONTENT_CHARS = 6000
MAX_MEMORY_BODY_CHARS = 1200

CODE_FILE_EXTS = re.compile(r"\.(py|ts|tsx|js|jsx|go|rs|rb|java|kt|swift|mjs|cjs)$")
TEST_FILE = re.compile(
    r"(?:^|/)test_[^/]*\.py$|_test\.py$|(?:^|/)tests?/|\.(?:test|spec)\.[jt]sx?$"
)

# Env for nested `claude -p` judge calls: suppress both judge hooks so a hook's
# own subprocess never re-triggers this hook or the prompt-behavior judge.
HOOK_ENV = {"CLAUDE_HOOK_NO_CHECK": "1", "CLAUDE_JUDGE_RUNNING": "1"}


def extract_change(payload: dict) -> tuple[str, str, str]:
    tool = payload.get("tool_name", "")
    inputs = payload.get("tool_input", {}) or {}
    if tool == "Edit":
        return (
            inputs.get("new_string", "") or "",
            inputs.get("old_string", "") or "",
            inputs.get("file_path", "") or "",
        )
    if tool == "Write":
        return inputs.get("content", "") or "", "", inputs.get("file_path", "") or ""
    if tool == "NotebookEdit":
        return inputs.get("new_source", "") or "", "", inputs.get("notebook_path", "") or ""
    return "", "", ""


def extract_bash_change(payload: dict) -> tuple[str, str, str]:
    command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    writes_code = bool(REDIRECT_TO_CODE_FILE.search(command)) or (
        bool(INPLACE_CODE_WRITER.search(command)) and bool(CODE_FILE_IN_COMMAND.search(command))
    )
    if not writes_code:
        return "", "", ""
    match = CODE_FILE_IN_COMMAND.search(command)
    return command, "", (match.group(0) if match else "")


def git_head_content(file_path: str) -> str:
    directory = os.path.dirname(file_path) or "."
    try:
        relative = subprocess.run(
            ["git", "-C", directory, "ls-files", "--full-name", "--", file_path],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if not relative:
            return ""
        return subprocess.run(
            ["git", "-C", directory, "show", f"HEAD:{relative}"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return ""


def run_haiku(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **HOOK_ENV},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def applies_to_code(body: str) -> bool:
    if not body.startswith("---"):
        return False
    parts = body.split("---", 2)
    if len(parts) < 3:
        return False
    for line in parts[1].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "apply":
            return "code" in value
    return False


def load_code_feedback_memories() -> list[tuple[str, str]]:
    if not MEMORY_DIR.is_dir():
        return []
    out = []
    for path in sorted(MEMORY_DIR.glob("feedback_*.md")):
        try:
            body = path.read_text()
        except OSError:
            continue
        if applies_to_code(body):
            out.append((path.name, body[:MAX_MEMORY_BODY_CHARS]))
    return out


def judge_code_style(
    content: str,
    previous: str,
    existing: str,
    file_path: str,
    memories: list[tuple[str, str]],
) -> list[str]:
    memory_block = "\n\n".join(f"=== {name} ===\n{body}" for name, body in memories)
    replaced_block = (
        previous[:MAX_CONTENT_CHARS]
        if previous
        else "(none - new file or full-file write; see COMMITTED FILE below)"
    )
    committed_block = (
        existing[:MAX_CONTENT_CHARS]
        if existing
        else "(none - file is untracked or new; treat all content as newly added)"
    )
    prompt = f"""You are a strict code reviewer. Below is content the assistant just wrote into a file, the text that content REPLACED, the current COMMITTED version of the file, and code-style feedback rules from the user.

Identify which (if any) rules the assistant's NEWLY ADDED code clearly violates.

Only flag a violation in code the assistant ADDED. Any identifier, line, comment, or construct that also appears in REPLACED CONTENT or in the COMMITTED FILE is pre-existing that the assistant merely kept, moved, or restored while editing. Do NOT flag pre-existing text, even if it violates a rule. A comment or identifier present in the COMMITTED FILE is pre-existing even when it is absent from REPLACED CONTENT (the assistant may be restoring or relocating it). The naming rule in particular applies only to identifiers the assistant INTRODUCES, never to ones carried over from REPLACED CONTENT or the COMMITTED FILE. When both REPLACED CONTENT and COMMITTED FILE are "(none ...)", treat all content as newly added.

Be conservative. Only flag CLEAR violations. If you have to argue for the violation, don't flag it.

If a NEWLY ADDED pattern matches the surrounding codebase style and the rule says "don't write it", still flag it. The rules override codebase convention.

Output format: filenames of violated rules, one per line, no prefix or commentary. If no rules are clearly violated, output exactly:
NONE

===== FILE =====
{file_path}

===== REPLACED CONTENT (pre-existing, never flag) =====
{replaced_block}

===== COMMITTED FILE (pre-existing in git HEAD, never flag) =====
{committed_block}

===== CONTENT WRITTEN =====
{content[:MAX_CONTENT_CHARS]}

===== FEEDBACK RULES =====
{memory_block}

===== VIOLATED FILENAMES (one per line, or NONE) ====="""
    verdict = run_haiku(prompt)
    if not verdict or verdict.upper().splitlines()[0].strip() == "NONE":
        return []
    return [
        line.strip()
        for line in verdict.splitlines()
        if line.strip().startswith("feedback_") and line.strip().endswith(".md")
    ]


def judge_bash_command(command: str, memories: list[tuple[str, str]]) -> list[str]:
    memory_block = "\n\n".join(f"=== {name} ===\n{body}" for name, body in memories)
    prompt = f"""You are a strict code reviewer. Below is a bash command the assistant just ran, and code-style feedback rules from the user.

Many bash commands write or modify source code (heredoc into a file, sed -i, redirect into a file, echo/printf into a file, python open()/write). If this command writes code that clearly violates a rule, output the violated rule filenames, one per line. Judge only the code the command introduces.

If the command does not write or modify code, or the code it writes violates nothing, output exactly:
NONE

Be conservative. Only flag CLEAR violations. If you have to argue for it, don't flag it.

===== BASH COMMAND =====
{command[:MAX_CONTENT_CHARS]}

===== FEEDBACK RULES =====
{memory_block}

===== VIOLATED FILENAMES (one per line, or NONE) ====="""
    verdict = run_haiku(prompt)
    if not verdict or verdict.upper().splitlines()[0].strip() == "NONE":
        return []
    return [
        line.strip()
        for line in verdict.splitlines()
        if line.strip().startswith("feedback_") and line.strip().endswith(".md")
    ]


def judge_test_weakening(previous: str, content: str) -> bool:
    prompt = f"""You are reviewing one Edit to a test file. Below is the exact text the edit REPLACED (PREVIOUS) and the text it WROTE (NEW).

Did this edit weaken the test? Weakening means any of:
- removing an assertion
- loosening a predicate (e.g. `assert x == 42` becomes `assert x`)
- swapping a strict assertion for a looser one (e.g. `assert_called_with(...)` becomes `assert_called()`)
without replacing it with an equal-or-stronger check.

Adding assertions, or replacing an assertion with a stronger one, is NOT weakening.

===== PREVIOUS =====
{previous[:MAX_CONTENT_CHARS]}

===== NEW =====
{content[:MAX_CONTENT_CHARS]}

Answer on the final line exactly, nothing after it:
VERDICT: WEAKENED
or
VERDICT: OK"""
    verdict = re.sub(r"[*`_]", "", run_haiku(prompt))
    matches = re.findall(r"VERDICT:\s*(WEAKENED|OK)", verdict, re.IGNORECASE)
    return bool(matches) and matches[-1].upper() == "WEAKENED"


def main() -> int:
    if os.environ.get("CLAUDE_HOOK_NO_CHECK") == "1":
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = payload.get("tool_name", "")
    memories = load_code_feedback_memories()
    if not memories:
        return 0

    flagged: list[str] = []
    target = ""

    if tool == "Bash":
        command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
        if not command:
            return 0
        target = "bash command"
        flagged.extend(judge_bash_command(command, memories))
    elif tool in {"Edit", "Write", "NotebookEdit"}:
        content, previous, file_path = extract_change(payload)
        if not content or not file_path or not CODE_FILE_EXTS.search(file_path):
            return 0
        target = f"edit to {file_path}"
        existing = git_head_content(file_path)
        flagged.extend(judge_code_style(content, previous, existing, file_path, memories))
        if previous and TEST_FILE.search(file_path) and judge_test_weakening(previous, content):
            flagged.append("feedback_no_test_weakening.md")
    else:
        return 0

    flagged = list(dict.fromkeys(flagged))
    if not flagged:
        return 0

    print(
        f"[edit-check] Your {target} appears to violate the following feedback rule(s):\n"
        + "\n".join(f"  - {name}" for name in flagged)
        + f"\n\nRe-read the rule(s) at {MEMORY_DIR}. If the flagged code is something "
        "you newly added, revert it. \"It matches the surrounding convention\", \"a "
        "docstring is not a comment\", and \"it is useful here\" are NOT valid reasons "
        "to keep it: these rules override codebase convention. Only dismiss this as a "
        "false positive if the flagged code is pre-existing text you merely moved or "
        "kept while editing.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
