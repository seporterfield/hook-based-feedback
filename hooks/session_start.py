#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import guard_active, memory_dir, sync_feedback_repo


def start_warm_judge() -> None:
    if os.environ.get("WARM_JUDGE") != "1":
        return
    daemon = memory_dir() / "tools" / "warm_judge" / "warm_judge.py"
    if not daemon.is_file():
        return
    digest = hashlib.md5(str(memory_dir()).encode()).hexdigest()[:8]
    path = Path(f"/tmp/warm-judge-{os.getuid()}-{digest}.sock")
    if path.exists():
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(1)
            probe.connect(str(path))
            probe.close()
            return
        except OSError:
            path.unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(daemon), "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    if guard_active():
        return 0
    sync_feedback_repo()
    start_warm_judge()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
