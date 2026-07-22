#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone

CONVERSATION_TYPES = ("user", "assistant")

SYSTEM_TEXT_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "Stop hook feedback",
    "hook feedback:",
    "[Request interrupted",
    "<command-name>",
    "<local-command-stdout>",
    "Caveat:",
)


def parse_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def content_blocks(message):
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def message_text(message):
    parts = []
    for block in content_blocks(message):
        if block.get("type") == "text":
            parts.append(block.get("text") or "")
    return " ".join(parts).strip()


def output_tokens(entry):
    usage = entry.get("message", {}).get("usage") or {}
    return usage.get("output_tokens")


def load_conversation(path, include_sidechain):
    entries = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") not in CONVERSATION_TYPES:
                continue
            if obj.get("isSidechain") and not include_sidechain:
                continue
            timestamp = parse_timestamp(obj.get("timestamp"))
            if timestamp is None:
                continue
            obj["_timestamp"] = timestamp
            entries.append(obj)
    entries.sort(key=lambda item: item["_timestamp"])
    return entries


def tool_use_names(entries):
    mapping = {}
    for entry in entries:
        for block in content_blocks(entry.get("message", {})):
            if block.get("type") == "tool_use":
                mapping[block.get("id")] = block.get("name") or "unknown"
    return mapping


def classify(entry):
    role = entry.get("type")
    message = entry.get("message", {})
    blocks = content_blocks(message)
    if role == "assistant":
        return "inference", None
    tool_results = [block for block in blocks if block.get("type") == "tool_result"]
    if tool_results:
        return "tool", tool_results
    if entry.get("isMeta"):
        return "system_wait", None
    text = message_text(message)
    if any(text.startswith(marker) for marker in SYSTEM_TEXT_MARKERS):
        return "system_wait", None
    if "hook feedback" in text:
        return "system_wait", None
    return "human_wait", None


def build_rows(entries, id_to_tool):
    rows = []
    origin = entries[0]["_timestamp"] if entries else None
    previous = None
    for entry in entries:
        timestamp = entry["_timestamp"]
        delta = (timestamp - previous).total_seconds() if previous is not None else 0.0
        previous = timestamp
        kind, payload = classify(entry)
        message = entry.get("message", {})
        if kind == "tool":
            first_name = id_to_tool.get(payload[0].get("tool_use_id"), "unknown")
            category = "tool:" + first_name
            extra = "" if len(payload) == 1 else " (+%d batched)" % (len(payload) - 1)
            detail = first_name + extra
        elif kind == "inference":
            category = "inference"
            names = [
                block.get("name")
                for block in content_blocks(message)
                if block.get("type") == "tool_use"
            ]
            detail = ("-> " + ", ".join(names)) if names else preview(message_text(message))
        else:
            category = kind
            detail = preview(message_text(message))
        rows.append(
            {
                "offset": (timestamp - origin).total_seconds(),
                "delta": delta,
                "category": category,
                "detail": detail,
                "output_tokens": output_tokens(entry),
            }
        )
    return rows


def preview(text, width=64):
    collapsed = " ".join(text.split())
    return collapsed[:width]


def render_trace(rows, absolute, limit):
    lines = []
    header = "%9s %8s  %-40s %-44s %7s" % (
        "t+ (s)",
        "delta",
        "category",
        "detail",
        "out_tok",
    )
    lines.append(header)
    lines.append("-" * len(header))
    shown = rows if not limit else rows[:limit]
    for row in shown:
        tokens = row["output_tokens"]
        lines.append(
            "%9.0f %8.1f  %-40.40s %-44.44s %7s"
            % (
                row["offset"],
                row["delta"],
                row["category"],
                row["detail"],
                "" if tokens is None else tokens,
            )
        )
    if limit and len(rows) > limit:
        lines.append("... (%d more rows)" % (len(rows) - limit))
    return "\n".join(lines)


def aggregate(rows):
    totals = OrderedDict()
    for row in rows:
        bucket = totals.setdefault(row["category"], {"seconds": 0.0, "calls": 0})
        bucket["seconds"] += row["delta"]
        bucket["calls"] += 1
    return sorted(totals.items(), key=lambda item: item[1]["seconds"], reverse=True)


def render_report(rows):
    ranked = aggregate(rows)
    wall = sum(row["delta"] for row in rows)
    lines = []
    lines.append(
        "total wall clock: %.0fs (%.1f min) across %d steps" % (wall, wall / 60, len(rows))
    )
    lines.append("")
    header = "%-40s %10s %7s %9s %7s" % ("category", "seconds", "calls", "avg_s", "%wall")
    lines.append(header)
    lines.append("-" * len(header))
    for category, bucket in ranked:
        seconds = bucket["seconds"]
        calls = bucket["calls"]
        share = (100 * seconds / wall) if wall else 0.0
        lines.append(
            "%-40.40s %10.0f %7d %9.1f %6.1f%%"
            % (category, seconds, calls, seconds / calls if calls else 0.0, share)
        )
    return "\n".join(lines)


def resolve_path(target):
    if os.path.isfile(target):
        return target
    matches = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/%s.jsonl" % target)))
    if matches:
        return matches[0]
    raise SystemExit("session log not found: %s" % target)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="session_trace")
    sub = parser.add_subparsers(dest="command", required=True)

    trace_parser = sub.add_parser("trace")
    trace_parser.add_argument("session")
    trace_parser.add_argument("--include-sidechain", action="store_true")
    trace_parser.add_argument("--absolute", action="store_true")
    trace_parser.add_argument("--limit", type=int, default=0)

    report_parser = sub.add_parser("report")
    report_parser.add_argument("session")
    report_parser.add_argument("--include-sidechain", action="store_true")

    args = parser.parse_args(argv)
    path = resolve_path(args.session)
    entries = load_conversation(path, args.include_sidechain)
    if not entries:
        raise SystemExit("no conversation entries with timestamps in: %s" % path)
    id_to_tool = tool_use_names(entries)
    rows = build_rows(entries, id_to_tool)

    if args.command == "trace":
        print(render_trace(rows, args.absolute, args.limit))
    else:
        print(render_report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
