#!/usr/bin/env python3
"""Score an ops agent's diagnosis against Fawlty Tower ground truth.

Baseline keyword grader: dependency-free and deterministic. For nuanced
grading (reasoning quality, remediation) feed `fawlty explain <guest>` plus
the diagnosis to an LLM judge; this tool is the cheap first gate for CI.

    grade.py <guest> <file|->  [--threshold 0.67] [--strict] [--json]
    grade.py --show <guest>
    grade.py --list
"""
import argparse
import json
import sys
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios" / "scenarios.json"


def load():
    with SCENARIOS.open(encoding="utf-8") as fh:
        return json.load(fh)["guests"]


def grade(scenario, text):
    low = text.lower()
    groups = []
    for group in scenario["required"]:
        hit = next((p for p in group if p in low), None)
        groups.append({"any_of": group, "matched": hit})
    matched = sum(1 for g in groups if g["matched"])
    warnings = [m for m in scenario.get("misdiagnoses", []) if m in low]
    return {
        "score": matched / len(groups),
        "groups": groups,
        "warnings": warnings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("guest", nargs="?")
    ap.add_argument("source", nargs="?", help="diagnosis file, or - for stdin")
    ap.add_argument("--threshold", type=float, default=0.67)
    ap.add_argument("--strict", action="store_true", help="misdiagnosis phrases also fail the run")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", action="store_true", help="print the scenario and exit")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    scenarios = load()
    if args.list:
        for name, sc in scenarios.items():
            print(f"{name:10s} {sc['tier']:8s} {sc['fault']}")
        return 0
    if not args.guest:
        ap.error("guest is required")
    if args.guest not in scenarios:
        print(f"unknown guest '{args.guest}'. Known: {', '.join(scenarios)}", file=sys.stderr)
        return 2
    sc = scenarios[args.guest]

    if args.show:
        print(json.dumps({args.guest: sc}, indent=2))
        return 0
    if not args.source:
        ap.error("diagnosis file (or -) is required")

    text = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    result = grade(sc, text)
    passed = result["score"] >= args.threshold and not (args.strict and result["warnings"])
    result.update(guest=args.guest, passed=passed, threshold=args.threshold)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.guest}: score {result['score']:.2f} (threshold {args.threshold}) -> {'PASS' if passed else 'FAIL'}")
        for g in result["groups"]:
            mark = "ok " if g["matched"] else "MISS"
            print(f"  [{mark}] {' | '.join(g['any_of'])}")
        for w in result["warnings"]:
            print(f"  [warn] mentions common misdiagnosis: '{w}'")
        print(f"  expected root cause: {sc['root_cause']}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
