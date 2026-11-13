"""User-run check of TBR_enumeration against tbr_reference (NOT executed by its author).

Run from the project root (the folder that contains src/):
    python probes/tbr_enum/check_tbr_enum.py
    python probes/tbr_enum/check_tbr_enum.py --cases 3000 --max-nodes 8 --seed 7
It reads nothing, writes nothing and uses no network. Exit code 0 = PASS, 1 = FAIL.
The hand fixtures below were derived by hand (PLAN_CHECK_T125.md); a fixture failure may
also be an error of that hand trace, so read the printed values before concluding.
Pass here would show agreement on small random graphs only, not correctness in general.
Random cases (T127, D-05): TBR_enumeration gets a large per-call budget (RANDOM_CALL_BUDGET).
A case in which either side is incomplete (the policy at that budget, or the reference, which
raises TBRSearchIncomplete at its own cap of 10 ** 7) is SKIPPED and COUNTED, never reported
as a mismatch; the skipped count is printed, and a run in which every case is skipped fails.
A larger --max-nodes makes the cost grow exponentially; the default 8 is small.
What this script does NOT prove: agreement on graphs larger than --max-nodes, equal expansion
counts on random graphs (only the four hand fixtures check counts), the wiring in the
simulator, the plan, the aggregation, the plots or the JSON round trip, and nothing about speed.
"""
import argparse
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from ssn_hops.tbr_enum import TBR_enumeration  # noqa: E402
from ssn_hops.tbr_reference import TBRSearchIncomplete, exhaustive_simple_path_reference  # noqa: E402

TICK = 5
RANDOM_CALL_BUDGET = 10 ** 7


def graph(n, edges):
    adjacency = np.zeros((n, n), dtype=bool)
    for a, b in edges:
        adjacency[a, b] = adjacency[b, a] = True
    return adjacency


def decide(policy, adjacency, location, destination, visited, permitted):
    packet = SimpleNamespace(location=location, destination=destination, visited=set(visited))
    context = SimpleNamespace(tick=TICK, adjacency=adjacency, permitted_neighbors=tuple(permitted))
    decision = policy.choose(packet, context)
    if decision is None:
        return None
    if type(decision.neighbor) is not int or decision.not_before_tick != TICK:
        raise AssertionError("decision has a wrong type or tick: %r" % (decision,))
    return decision.neighbor


def reference_decision(adjacency, location, destination, visited, permitted):
    result = exhaustive_simple_path_reference(
        adjacency, location, destination, permitted_first_hops=permitted, visited=visited,
        max_nodes=64, max_expansions=10 ** 7)
    if result.path is None or len(result.path) == 1:
        return None
    return result.path[1]


def algebra_problems(stats):
    problems = []
    completed = stats["complete_route"] + stats["complete_no_route"] + stats["complete_zero_hop"]
    if stats["policy_calls"] != completed + stats["incomplete_call_budget"] + stats["skipped_after_cell_budget"]:
        problems.append("call algebra")
    if stats["total_expansions"] != stats["complete_expansions_sum"] + stats["incomplete_expansions_sum"]:
        problems.append("expansion algebra")
    if stats["incomplete_expansions_sum"] != stats["incomplete_call_budget"] * stats["max_call_expansions"]:
        problems.append("incomplete calls must enter exactly max_call_expansions prefixes")
    json.dumps(stats, allow_nan=False)
    return problems


def random_case(rng, n):
    p = rng.choice((0.2, 0.35, 0.5, 0.8))
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    adjacency = graph(n, edges)
    location = rng.randrange(n)
    destination = rng.randrange(n)
    others = [v for v in range(n) if v not in (location, destination)]
    visited = {location} | {v for v in others if rng.random() < 0.25}
    permitted = [v for v in range(n) if adjacency[location, v] and rng.random() < 0.7]
    return adjacency, location, destination, visited, permitted


def random_comparison(cases, max_nodes, seed):
    rng = random.Random(seed)
    bad = []
    skipped = 0
    for number in range(cases):
        n = rng.randrange(2, max_nodes + 1)
        adjacency, location, destination, visited, permitted = random_case(rng, n)
        try:
            expected = reference_decision(adjacency, location, destination, visited, permitted)
        except TBRSearchIncomplete:
            skipped += 1
            continue
        policy = TBR_enumeration(max_call_expansions=RANDOM_CALL_BUDGET)
        got = decide(policy, adjacency, location, destination, visited, permitted)
        if policy.stats()["incomplete_call_budget"]:
            skipped += 1
            continue
        if got != expected:
            bad.append((number, n, location, destination, sorted(visited), permitted, expected, got))
    return bad, skipped


def hand_fixtures():
    # (name, graph, location, destination, visited, permitted, decision, total_expansions)
    fixtures = [
        ("counterexample 1", graph(5, [(0, 1), (0, 2), (0, 4), (2, 3), (3, 4)]), 0, 4, {0}, (1, 2), 2, 12),
        ("counterexample 2", graph(5, [(0, 2), (0, 4), (2, 3), (3, 4)]), 2, 4, {0, 2}, (0, 3), 3, 5),
        ("K4 with node 3 busy", graph(4, [(a, b) for a in range(4) for b in range(a + 1, 4)]), 0, 3, {0}, (1, 2), 1, 10),
        ("no route", graph(4, [(0, 1), (1, 2)]), 0, 3, {0}, (1,), None, 8),
    ]
    problems = []
    for name, adjacency, location, destination, visited, permitted, decision, expansions in fixtures:
        policy = TBR_enumeration()
        got = decide(policy, adjacency, location, destination, visited, permitted)
        stats = policy.stats()
        if got != decision or stats["total_expansions"] != expansions:
            problems.append("%s: decision %r (hand %r), expansions %r (hand %r)"
                            % (name, got, decision, stats["total_expansions"], expansions))
        problems.extend(name + ": " + text for text in algebra_problems(stats))
    return problems


def budget_checks():
    problems = []
    chain = graph(4, [(0, 1), (1, 2), (2, 3)])
    policy = TBR_enumeration(max_call_expansions=1)
    got = decide(policy, chain, 0, 3, {0}, (1,))
    stats = policy.stats()
    if got is not None:
        problems.append("an incomplete call returned a route: %r" % (got,))
    if (stats["incomplete_call_budget"], stats["policy_calls"], stats["completeness_share"]) != (1, 1, 0.0):
        problems.append("incomplete call not counted as expected: %r" % (stats,))
    problems.extend("per-call budget: " + text for text in algebra_problems(stats))
    policy = TBR_enumeration(max_call_expansions=1000, max_cell_expansions=1)
    first = decide(policy, chain, 0, 3, {0}, (1,))
    second = decide(policy, chain, 0, 3, {0}, (1,))
    stats = policy.stats()
    if first != 1 or second is not None:
        problems.append("cell budget: first %r (expected 1), second %r (expected None)" % (first, second))
    if not stats["cell_budget_exhausted"] or stats["skipped_after_cell_budget"] != 1:
        problems.append("cell budget not reported as exhausted/skipped: %r" % (stats,))
    problems.extend("cell budget: " + text for text in algebra_problems(stats))
    for bad in (0, -1, True, 1.5):
        try:
            TBR_enumeration(max_call_expansions=bad)
        except ValueError:
            continue
        problems.append("budget %r was accepted" % (bad,))
    return problems


def main():
    parser = argparse.ArgumentParser(description="compare TBR_enumeration with tbr_reference")
    parser.add_argument("--cases", type=int, default=2000)
    parser.add_argument("--max-nodes", type=int, default=8)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    if args.cases < 1 or args.max_nodes < 2:
        parser.error("--cases must be >= 1 and --max-nodes >= 2")
    failures = []
    bad, skipped = random_comparison(args.cases, args.max_nodes, args.seed)
    print("random comparison: %d cases, %d compared, %d skipped (a side was incomplete), %d mismatches"
          % (args.cases, args.cases - skipped, skipped, len(bad)))
    for item in bad[:5]:
        print("  MISMATCH case=%d n=%d location=%d destination=%d visited=%s permitted=%s reference=%r enum=%r" % item)
    if bad:
        failures.append("random comparison")
    if skipped == args.cases:
        failures.append("random comparison (every case was skipped)")
    for label, problems in (("hand fixtures", hand_fixtures()), ("budget rules", budget_checks())):
        print("%s: %d problems" % (label, len(problems)))
        for text in problems:
            print("  PROBLEM " + text)
        if problems:
            failures.append(label)
    print("FAIL: " + ", ".join(failures) if failures else "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
