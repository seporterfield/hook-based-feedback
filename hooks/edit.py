#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import guard_active

EDIT_CHECKS = ["check-edit-feedback.py"]


def main() -> int:
    if guard_active():
        return 0
    raw = sys.stdin.buffer.read()
    here = Path(__file__).parent
    blocked = False
    for check in EDIT_CHECKS:
        result = subprocess.run(
            ["python3", str(here / check)],
            input=raw,
            capture_output=True,
        )
        if result.stdout:
            sys.stdout.buffer.write(result.stdout)
        if result.returncode == 2:
            blocked = True
            if result.stderr:
                sys.stderr.buffer.write(result.stderr)
    return 2 if blocked else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
