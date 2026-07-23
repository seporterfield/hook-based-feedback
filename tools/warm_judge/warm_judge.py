#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_RESPONSE_CHARS = 6000
MAX_RULE_BODY_CHARS = 1200
SLOT_MAX_AGE_S = 900
IDLE_SHUTDOWN_S = 1800
JUDGE_TIMEOUT_S = 60
CLIENT_TIMEOUT_S = 75

PRIMING_TEMPLATE = """You are a strict reviewer on standby. Memorize the feedback rules below.
In later messages I will send you an assistant's response to a user. For each one,
identify which (if any) of the feedback rules the response clearly violates.
Be conservative. Only flag CLEAR violations. If you have to argue for the
violation, don't flag it.
Reply to each with the violated rule filenames, one per line, with no prefix
and no commentary. If no rules are clearly violated, reply exactly: NONE
Reply to THIS message with exactly: READY

===== FEEDBACK RULES =====
{rules}"""

JUDGMENT_TEMPLATE = """===== ASSISTANT RESPONSE TO JUDGE =====
{response}
===== VIOLATED FILENAMES (one per line, or NONE) ====="""


def memory_dir() -> Path:
    override = os.environ.get("AGENT_MEMORY_DIR")
    if override:
        return Path(override).expanduser()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    mangled = str(Path(project).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / mangled / "memory"


def socket_path(directory: Path) -> Path:
    digest = hashlib.md5(str(directory).encode()).hexdigest()[:8]
    return Path(f"/tmp/warm-judge-{os.getuid()}-{digest}.sock")


def load_rules(directory: Path) -> str:
    blocks = []
    for path in sorted(directory.glob("feedback_*.md")):
        try:
            body = path.read_text().replace("\x00", "")
        except OSError:
            continue
        blocks.append(f"=== {path.name} ===\n{body[:MAX_RULE_BODY_CHARS]}")
    return "\n\n".join(blocks)


class Slot:
    def __init__(self, rules: str):
        self.primed = threading.Event()
        self.created_at = time.monotonic()
        self.process = subprocess.Popen(
            [
                "claude", "-p",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--verbose",
                "--model", "haiku",
                "--effort", "low",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={**os.environ, "CLAUDE_HOOK_NO_CHECK": "1"},
        )
        threading.Thread(target=self.prime, args=(rules,), daemon=True).start()

    def prime(self, rules: str) -> None:
        try:
            self.send_text(PRIMING_TEMPLATE.format(rules=rules))
            self.wait_result(JUDGE_TIMEOUT_S)
            self.primed.set()
        except Exception:
            self.kill()

    def send_text(self, text: str) -> None:
        self.process.stdin.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": text},
        }) + "\n")
        self.process.stdin.flush()

    def wait_result(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("slot process exited")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                return event
        raise TimeoutError("no result event before deadline")

    def judge(self, response: str) -> str:
        self.send_text(JUDGMENT_TEMPLATE.format(response=response[:MAX_RESPONSE_CHARS]))
        return self.wait_result(JUDGE_TIMEOUT_S).get("result", "NONE")

    def alive(self) -> bool:
        return self.process.poll() is None

    def kill(self) -> None:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.terminate()
        except OSError:
            pass


class Pool:
    def __init__(self, rules_dir: Path, spares: int):
        self.rules_dir = rules_dir
        self.spares = spares
        self.lock = threading.Lock()
        self.slots: list[Slot] = []
        self.last_judgment = time.monotonic()
        self.refill()

    def refill(self) -> None:
        with self.lock:
            self.slots = [s for s in self.slots if s.alive()]
            missing = self.spares - len(self.slots)
            if missing <= 0:
                return
            rules = load_rules(self.rules_dir)
            for _ in range(missing):
                self.slots.append(Slot(rules))

    def take(self) -> Slot | None:
        self.last_judgment = time.monotonic()
        with self.lock:
            for index, slot in enumerate(self.slots):
                if slot.alive() and slot.primed.is_set():
                    return self.slots.pop(index)
        return None

    def recycle_stale(self) -> None:
        with self.lock:
            fresh, stale = [], []
            for slot in self.slots:
                age = time.monotonic() - slot.created_at
                (stale if age > SLOT_MAX_AGE_S else fresh).append(slot)
            self.slots = fresh
        for slot in stale:
            slot.kill()
        self.refill()

    def status(self) -> dict:
        with self.lock:
            return {
                "slots": len(self.slots),
                "primed": sum(1 for s in self.slots if s.primed.is_set()),
            }


def serve(arguments: argparse.Namespace) -> int:
    directory = memory_dir()
    path = socket_path(directory)
    if path.exists():
        path.unlink()
    pool = Pool(directory, arguments.spares)
    shutdown = threading.Event()

    def maintain() -> None:
        while not shutdown.is_set():
            shutdown.wait(30)
            if time.monotonic() - pool.last_judgment > IDLE_SHUTDOWN_S:
                shutdown.set()
                server.shutdown()
                return
            pool.recycle_stale()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request_payload = json.loads(self.rfile.readline())
            except (ValueError, OSError):
                return
            command = request_payload.get("command", "judge")
            if command == "status":
                reply = pool.status()
            elif command == "shutdown":
                reply = {"ok": True}
                shutdown.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                reply = self.run_judgment(request_payload.get("response", ""))
            self.wfile.write(json.dumps(reply).encode() + b"\n")

        def run_judgment(self, response: str) -> dict:
            slot = pool.take()
            threading.Thread(target=pool.refill, daemon=True).start()
            if slot is None:
                return {"error": "no primed slot"}
            try:
                verdict = slot.judge(response)
            except Exception as error:
                return {"error": str(error)}
            finally:
                slot.kill()
                threading.Thread(target=pool.refill, daemon=True).start()
            return {"verdict": verdict}

    with socketserver.ThreadingUnixStreamServer(str(path), Handler) as server:
        threading.Thread(target=maintain, daemon=True).start()
        server.serve_forever()
    for slot in pool.slots:
        slot.kill()
    path.unlink(missing_ok=True)
    return 0


def request(payload: dict, timeout: float) -> dict:
    path = socket_path(memory_dir())
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(str(path))
    connection.sendall(json.dumps(payload).encode() + b"\n")
    chunks = []
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            break
    connection.close()
    return json.loads(b"".join(chunks))


def judge(arguments: argparse.Namespace) -> int:
    response = arguments.response if arguments.response is not None else sys.stdin.read()
    reply = request({"command": "judge", "response": response}, CLIENT_TIMEOUT_S)
    if "error" in reply:
        print(reply["error"], file=sys.stderr)
        return 1
    print(reply.get("verdict", "NONE"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve")
    serve_parser.add_argument("--spares", type=int, default=1)
    judge_parser = commands.add_parser("judge")
    judge_parser.add_argument("--response")
    commands.add_parser("status")
    commands.add_parser("stop")
    arguments = parser.parse_args()

    if arguments.command == "serve":
        return serve(arguments)
    if arguments.command == "judge":
        return judge(arguments)
    if arguments.command == "status":
        print(json.dumps(request({"command": "status"}, 5)))
        return 0
    if arguments.command == "stop":
        print(json.dumps(request({"command": "shutdown"}, 5)))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
