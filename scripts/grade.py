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
import re
import sys
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios" / "scenarios.json"

# A phrase must start on a word boundary, so "healthy" does not match inside
# "unhealthy" and "oom" does not match inside "headroom". The END is left open
# on purpose so stems such as "throttl" or "reconcil" keep working.
_LEFT_EDGE = r"(?<![a-z0-9])"

# A hit preceded (within the same clause) by one of these is treated as
# negated: "the pod is not OOMKilled" must not count as an OOM diagnosis.
_NEGATORS = {"not", "no", "never", "without", "nothing", "none", "neither", "nor",
             "isn't", "wasn't", "aren't", "weren't", "doesn't", "didn't", "don't",
             "hasn't", "haven't", "hadn't", "can't", "cannot", "won't", "shouldn't",
             "rule", "rules", "ruled", "exclude", "excludes", "excluded", "excluding"}
_NEGATION_WINDOW = 5  # words to look back, within the clause
# Hard clause breaks: punctuation, and conjunctions that start a new claim
# ("not OOMKilled but CrashLoopBackOff", "never released until OOMKilled").
_CLAUSE_BREAK = re.compile(
    r"[.;:!?()\n]|\b(?:but|however|although|though|whereas|yet|instead|rather|and|until|while|because|so)\b"
)
# Words that may sit between a comma and the phrase without ending the list:
# "no restarts, CrashLoopBackOff or OOMKilled" negates all three.
_LIST_GLUE = {"or", "nor", "any"}
_LIST_ITEM_WORDS = 3  # longest comma-separated item still read as a list entry
_WORD = re.compile(r"[a-z']+")


def _is_negated(text, start):
    clause = _CLAUSE_BREAK.split(text[:start])[-1]
    segments = clause.split(",")
    scope = [segments.pop()]
    # A comma ends the negation's reach unless the phrase is the tail of a
    # list: what sits between the last comma and the phrase is nothing or a
    # short or/nor joiner ("no restarts, CrashLoopBackOff, or OOMKilled").
    # Once in a list, earlier short items keep it going; a longer segment is
    # a new claim ("not OOMKilled, the pod is in CrashLoopBackOff") and ends it.
    words = _WORD.findall(scope[0])
    in_list = not words or (len(words) <= _LIST_ITEM_WORDS and bool(_LIST_GLUE & set(words)))
    while in_list and segments:
        scope.insert(0, segments.pop())
        in_list = len(_WORD.findall(scope[0])) <= _LIST_ITEM_WORDS
    # The look-back window is measured from the start of the list, so a long
    # list cannot push the negator out of reach; list items do not count.
    words = _WORD.findall(scope[0])[-_NEGATION_WINDOW:] + _WORD.findall(" ".join(scope[1:]))
    return any(w in _NEGATORS for w in words)


def find(phrase, text):
    """Return "hit", "negated" or None for `phrase` in lower-cased `text`."""
    seen_negated = False
    for m in re.finditer(_LEFT_EDGE + re.escape(phrase), text):
        if not _is_negated(text, m.start()):
            return "hit"
        seen_negated = True
    return "negated" if seen_negated else None


def load():
    with SCENARIOS.open(encoding="utf-8") as fh:
        return json.load(fh)["guests"]


def grade(scenario, text):
    low = text.lower().replace("\u2019", "'").replace("\u2018", "'")  # curly apostrophes
    groups = []
    negated = []
    for group in scenario["required"]:
        hit = None
        for p in group:
            state = find(p, low)
            if state == "hit":
                hit = p
                break
            if state == "negated":
                negated.append(p)
        groups.append({"any_of": group, "matched": hit})
    matched = sum(1 for g in groups if g["matched"])
    warnings = []
    for m in scenario.get("misdiagnoses", []):
        state = find(m, low)
        if state == "hit":
            warnings.append(m)
        elif state == "negated":
            negated.append(m)
    return {
        "score": matched / len(groups),
        "groups": groups,
        "warnings": warnings,
        "negated": negated,
        "negative_control": bool(scenario.get("negative_control")),
    }


def warnings_are_fatal(result, strict=False):
    """Misdiagnoses fail the run under --strict, and ALWAYS for a negative
    control: inventing a problem on a healthy workload is the failure mode a
    negative control exists to catch."""
    return bool(strict or result["negative_control"])


def passed(result, threshold, strict=False):
    fatal_warnings = warnings_are_fatal(result, strict) and result["warnings"]
    # Round so the documented 0.67 means "2 of 3": 2/3 is 0.6666... and used to fail.
    return round(result["score"], 2) >= threshold and not fatal_warnings


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
    ok = passed(result, args.threshold, args.strict)
    result.update(guest=args.guest, passed=ok, threshold=args.threshold)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.guest}: score {result['score']:.2f} (threshold {args.threshold}) -> {'PASS' if ok else 'FAIL'}")
        for g in result["groups"]:
            mark = "ok " if g["matched"] else "MISS"
            print(f"  [{mark}] {' | '.join(g['any_of'])}")
        mark = "FAIL" if warnings_are_fatal(result, args.strict) else "warn"
        for w in result["warnings"]:
            print(f"  [{mark}] mentions common misdiagnosis: '{w}'")
        for n in result["negated"]:
            print(f"  [info] ignored negated mention: '{n}'")
        print(f"  expected root cause: {sc['root_cause']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
