#!/usr/bin/env python3
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import session_trace as trace

FIXTURE = os.path.join(HERE, "fixture.jsonl")


def load(include_sidechain=False):
    entries = trace.load_conversation(FIXTURE, include_sidechain)
    return trace.build_rows(entries, trace.tool_use_names(entries))


def test_sidechain_excluded_by_default():
    rows_default = load(include_sidechain=False)
    rows_all = load(include_sidechain=True)
    assert len(rows_default) == 8
    assert len(rows_all) == 9


def test_chronological_deltas_and_categories():
    rows = load()
    observed = [(round(row["delta"]), row["category"]) for row in rows]
    expected = [
        (0, "human_wait"),
        (5, "inference"),
        (3, "tool:Bash"),
        (4, "inference"),
        (8, "system_wait"),
        (2, "inference"),
        (1, "tool:Read"),
        (100, "human_wait"),
    ]
    assert observed == expected


def test_output_tokens_captured_on_inference():
    rows = load()
    inference_tokens = [row["output_tokens"] for row in rows if row["category"] == "inference"]
    assert inference_tokens == [42, 10, 7]


def test_report_aggregate_descending_with_calls():
    rows = load()
    ranked = trace.aggregate(rows)
    observed = [
        (category, round(bucket["seconds"]), bucket["calls"])
        for category, bucket in ranked
    ]
    expected = [
        ("human_wait", 100, 2),
        ("inference", 11, 3),
        ("system_wait", 8, 1),
        ("tool:Bash", 3, 1),
        ("tool:Read", 1, 1),
    ]
    assert observed == expected


def test_report_totals_partition_wall_clock():
    rows = load()
    wall = sum(row["delta"] for row in rows)
    per_category = sum(bucket["seconds"] for _, bucket in trace.aggregate(rows))
    assert round(wall) == 123
    assert round(per_category) == round(wall)


def run():
    failures = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print("PASS", name)
            except AssertionError as error:
                failures += 1
                print("FAIL", name, error)
    if failures:
        print("%d failing test(s)" % failures)
        return 1
    print("all tests pass")
    return 0


if __name__ == "__main__":
    sys.exit(run())
