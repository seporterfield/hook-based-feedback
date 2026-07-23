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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_RESPONSE_CHARS = 6000
MAX_RULE_BODY_CHARS = 1200
SHARD_SIZE = 12
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


def load_shards(directory: Path) -> list[str]:
    blocks = []
    for path in sorted(directory.glob("feedback_*.md")):
        try:
            body = path.read_text().replace("\x00", "")
        except OSError:
            continue
        blocks.append(f"=== {path.name} ===\n{body[:MAX_RULE_BODY_CHARS]}")
    return [
        "\n\n".join(blocks[i : i + SHARD_SIZE])
        for i in range(0, len(blocks), SHARD_SIZE)
    ]


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
        self.shards: list[list[Slot]] = []
        self.last_judgment = time.monotonic()
        self.refill()

    def refill(self) -> None:
        shard_rules = load_shards(self.rules_dir)
        with self.lock:
            while len(self.shards) < len(shard_rules):
                self.shards.append([])
            del self.shards[len(shard_rules):]
            for index, rules in enumerate(shard_rules):
                slots = [slot for slot in self.shards[index] if slot.alive()]
                while len(slots) < self.spares:
                    slots.append(Slot(rules))
                self.shards[index] = slots

    def take_all(self) -> list[Slot] | None:
        self.last_judgment = time.monotonic()
        with self.lock:
            taken: list[tuple[int, Slot]] = []
            for index, slots in enumerate(self.shards):
                position = next(
                    (candidate_index for candidate_index, candidate in enumerate(slots)
                     if candidate.alive() and candidate.primed.is_set()),
                    None,
                )
                if position is None:
                    for shard_index, slot in taken:
                        self.shards[shard_index].append(slot)
                    return None
                taken.append((index, slots.pop(position)))
            return [slot for _, slot in taken]

    def recycle_stale(self) -> None:
        stale = []
        with self.lock:
            for index, slots in enumerate(self.shards):
                fresh = []
                for slot in slots:
                    age = time.monotonic() - slot.created_at
                    (stale if age > SLOT_MAX_AGE_S else fresh).append(slot)
                self.shards[index] = fresh
        for slot in stale:
            slot.kill()
        self.refill()

    def status(self) -> dict:
        with self.lock:
            return {
                "shards": len(self.shards),
                "slots": sum(len(slots) for slots in self.shards),
                "primed": sum(
                    1 for slots in self.shards
                    for slot in slots if slot.primed.is_set()
                ),
            }


def serve(arguments: argparse.Namespace) -> int:
    directory = memory_dir()
    path = socket_path(directory)
    if path.exists():
        path.unlink()
    pool = Pool(directory, arguments.spares)
    shutdown = threading.Event()

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
            slots = pool.take_all()
            if slots is None:
                return {"error": "not every shard has a primed slot"}
            try:
                with ThreadPoolExecutor(max_workers=len(slots)) as executor:
                    verdicts = list(
                        executor.map(lambda slot: slot.judge(response), slots)
                    )
            except Exception as error:
                return {"error": str(error)}
            finally:
                for slot in slots:
                    slot.kill()
                threading.Thread(target=pool.refill, daemon=True).start()
            lines: list[str] = []
            for verdict in verdicts:
                stripped = verdict.strip()
                if not stripped:
                    continue
                if stripped.splitlines()[0].strip().upper() == "NONE":
                    continue
                lines.extend(stripped.splitlines())
            return {"verdict": "\n".join(lines) if lines else "NONE"}

    def maintain() -> None:
        while not shutdown.is_set():
            shutdown.wait(30)
            if time.monotonic() - pool.last_judgment > IDLE_SHUTDOWN_S:
                shutdown.set()
                server.shutdown()
                return
            pool.recycle_stale()

    with socketserver.ThreadingUnixStreamServer(str(path), Handler) as server:
        bound_inode = os.stat(path).st_ino
        threading.Thread(target=maintain, daemon=True).start()
        server.serve_forever()
    for slots in pool.shards:
        for slot in slots:
            slot.kill()
    try:
        if os.stat(path).st_ino == bound_inode:
            path.unlink()
    except OSError:
        pass
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
