#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import guard_active, sync_feedback_repo


def main() -> int:
    if guard_active():
        return 0
    sync_feedback_repo()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
