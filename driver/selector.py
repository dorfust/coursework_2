"""Slice selector: slices.json (DATA) -> ordered train/trace/cell steps of ONE plan. Written, NOT run.

Item keys: kind (train | trace | cell), N, failure_probability (exact ==, no tolerance),
seed_tuple_indices (position in suite['seed_tuples']), policies, exclude_earlier, optional_policy_absent,
cap_minutes | cap_minutes_param. A selector that names a cell which is not in body['cells'] (absent by
design) or that selects nothing is REFUSED. check_partition asserts that the union of all slices equals
body['cells'] (and the planned trainings) with nothing twice.

Optional top-level key 'suite' (T068, P2-X1): the name of the suite the file belongs to (the plan body carries it as
body['suite']['name'], written by ssn_hops.experiments.make_plan from the suite file). check_suite_binding, called by
resolve_all (the one place every driver, status, pack and list_cells go through), refuses a plan made from another suite
with a SelectorError naming both names. An absent key is tolerated, and so is a plan body without a suite name
(the synthetic test plans of tests/synth.py); a non-string or empty value is refused (load_slices and resolve_all).

CLI (from the m1 directory; reads and validates the plan only):
  python -m driver.selector --plan <root>/plan.json --slices slices.json [--slice ID]
"""
import argparse
from collections import Counter
import json
import sys

SLICES_SCHEMA = "ssn-m1-slices-v1"
POLICY_NAMES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")
ITEM_KEYS = {"kind", "N", "failure_probability", "seed_tuple_indices", "policies", "exclude_earlier",
             "optional_policy_absent", "cap_minutes", "cap_minutes_param"}


class SelectorError(ValueError):
    """A slice definition or a selection against the plan is invalid."""


def _is_number(value):
    return type(value) in (int, float)


def _declared_suite(spec):
    """The optional top-level 'suite' name of a slices document (None when the key is absent)."""
    if "suite" not in spec:
        return None
    declared = spec["suite"]
    if not isinstance(declared, str) or not declared:
        raise SelectorError("the slices key 'suite' must be a nonempty string (the suite name of the plan)")
    return declared


def load_slices(source):
    """Parse (path or dict) and validate the slice definitions; returns the dict."""
    if not isinstance(source, dict):
        with open(source, encoding="utf-8") as handle:
            source = json.load(handle)
    spec = source
    if spec.get("schema") != SLICES_SCHEMA:
        raise SelectorError("unsupported slices schema")
    _declared_suite(spec)
    params = spec.get("parameters", {})
    if not isinstance(params, dict) or any(not _is_number(v) or v <= 0 for v in params.values()):
        raise SelectorError("parameters must map names to positive numbers")
    slices = spec.get("slices")
    if not isinstance(slices, list) or not slices:
        raise SelectorError("slices must be a nonempty list")
    if len({s.get("id") for s in slices}) != len(slices):
        raise SelectorError("duplicate slice id")
    for entry in slices:
        if not isinstance(entry.get("id"), str) or type(entry.get("counted")) is not bool:
            raise SelectorError("each slice needs a string id and a boolean counted flag")
        items = entry.get("items")
        if not isinstance(items, list) or not items:
            raise SelectorError(f"slice {entry['id']} has no items")
        for item in items:
            _check_item(entry["id"], item, params)
    return spec


def _check_item(slice_id, item, params):
    where = f"slice {slice_id}"
    if item.get("kind") not in ("train", "trace", "cell") or set(item) - ITEM_KEYS:
        raise SelectorError(f"{where}: bad item kind or unknown item keys")
    for key, check in (("N", lambda v: type(v) is int), ("seed_tuple_indices", lambda v: type(v) is int),
                       ("failure_probability", _is_number),
                       ("policies", lambda v: v in POLICY_NAMES)):
        if key in item:
            values = item[key]
            if not isinstance(values, list) or not values or not all(check(v) for v in values):
                raise SelectorError(f"{where}: {key} must be a nonempty list of valid values")
    if item["kind"] == "train" and set(item) - {"kind", "N"}:
        raise SelectorError(f"{where}: a train item takes only N")
    if item["kind"] != "cell" and set(item) & {"cap_minutes", "cap_minutes_param", "exclude_earlier",
                                               "optional_policy_absent"}:
        raise SelectorError(f"{where}: cap/exclude/optional keys belong to cell items only")
    if "cap_minutes" in item and "cap_minutes_param" in item:
        raise SelectorError(f"{where}: give cap_minutes or cap_minutes_param, not both")
    if "cap_minutes" in item and (not _is_number(item["cap_minutes"]) or item["cap_minutes"] <= 0):
        raise SelectorError(f"{where}: cap_minutes must be positive")
    if "cap_minutes_param" in item and item["cap_minutes_param"] not in params:
        raise SelectorError(f"{where}: cap_minutes_param names an undefined parameter")
    for flag in ("exclude_earlier", "optional_policy_absent"):
        if flag in item and type(item[flag]) is not bool:
            raise SelectorError(f"{where}: {flag} must be boolean")


def _matching_scenarios(view, item):
    ns, ps, idx = item.get("N"), item.get("failure_probability"), item.get("seed_tuple_indices")
    found = []
    for scenario in view.scenarios:
        if ns is not None and view.scenario_n(scenario) not in ns:
            continue
        if ps is not None and view.scenario_p(scenario) not in ps:
            continue
        if idx is not None and view.seed_index(scenario) not in idx:
            continue
        found.append(scenario)
    return found


def _cap_seconds(item, params):
    if "cap_minutes" in item:
        return float(item["cap_minutes"]) * 60.0
    if "cap_minutes_param" in item:
        return float(params[item["cap_minutes_param"]]) * 60.0
    return None


def resolve_item(view, item, params, taken):
    """Steps of one item. ``taken`` = cell ids already owned by earlier slices/items (exclude_earlier)."""
    kind = item["kind"]
    if kind == "train":
        steps = []
        for n in item["N"]:
            model = view.body["models"].get(str(n))
            if model is None or "GLR" not in view.body["policies"]:
                raise SelectorError(f"train N={n}: no GLR model of that N in the plan")
            if model.get("supplied"):
                raise SelectorError(f"train N={n}: the model is supplied, nothing to train")
            steps.append({"kind": "train", "id": f"train-n{n}", "n": str(n),
                          "step_ids": [s["id"] for s in model["steps"]]})
        return steps
    matched = _matching_scenarios(view, item)
    if kind == "trace":
        if not matched:
            raise SelectorError("trace item selects nothing")
        steps, seen = [], set()
        for scenario in matched:
            path = scenario["trace_path"]
            if path not in seen:
                seen.add(path)
                steps.append({"kind": "trace", "id": "trace-" + view.trace_owner_by_path[path]["id"],
                              "trace_path": path})
        return steps
    policies = item.get("policies")
    declared = view.body["policies"]
    if policies is not None:
        absent = [p for p in policies if p not in declared]
        if absent and item.get("optional_policy_absent") and len(absent) == len(policies):
            return []
        if absent:
            raise SelectorError(f"policies {absent} are not in the plan union {declared}")
    if not matched:
        raise SelectorError("cell item selects nothing (no scenario matches N/failure_probability/seed_tuple_indices)")
    ids = {s["id"] for s in matched}
    if policies is not None:
        for scenario in matched:
            for policy in policies:
                cell_id = scenario["id"] + "--" + policy
                if cell_id not in view.cell_by_id:
                    raise SelectorError(f"selector selects {cell_id}, which is not in body['cells'] (absent by design)")
    chosen = [c for c in view.cells if c["scenario"] in ids and (policies is None or c["policy"] in policies)]
    if item.get("exclude_earlier"):
        chosen = [c for c in chosen if c["id"] not in taken]
    if not chosen:
        raise SelectorError("cell item selects nothing")
    cap = _cap_seconds(item, params)
    return [{"kind": "cell", "id": c["id"], "scenario": c["scenario"], "policy": c["policy"],
             "trace_path": view.scenario_of(c)["trace_path"], "cap_seconds": cap} for c in chosen]


def check_suite_binding(view, spec):
    """T068 P2-X1: refuse a slice file whose 'suite' name differs from the suite name of the plan.

    Tolerated (no check): no 'suite' key in the slice file; a plan body without a string suite name (synthetic plans).
    """
    declared = _declared_suite(spec)
    suite = view.body.get("suite")
    planned = suite.get("name") if isinstance(suite, dict) else None
    if declared is not None and isinstance(planned, str) and planned != declared:
        raise SelectorError(f"the slice file is for suite {declared!r} but the plan was made from suite {planned!r}; "
                            f"use the slice file of this plan")


def resolve_all(view, spec):
    """Resolve every slice in file order; a cell owned twice is refused."""
    check_suite_binding(view, spec)
    params = spec.get("parameters", {})
    taken = {}
    resolved = {}
    for entry in spec["slices"]:
        steps = []
        for item in entry["items"]:
            for step in resolve_item(view, item, params, set(taken)):
                if step["kind"] == "cell":
                    if step["id"] in taken:
                        raise SelectorError(f"cell {step['id']} is selected by {taken[step['id']]} and {entry['id']}")
                    taken[step["id"]] = entry["id"]
                steps.append(step)
        if not steps:
            raise SelectorError(f"slice {entry['id']} selects nothing")
        traces = []
        for step in steps:
            if step["kind"] in ("cell", "trace") and step["trace_path"] not in traces:
                traces.append(step["trace_path"])
        resolved[entry["id"]] = {"id": entry["id"], "counted": entry["counted"], "steps": steps,
                                 "cell_ids": [s["id"] for s in steps if s["kind"] == "cell"],
                                 "train_ns": [s["n"] for s in steps if s["kind"] == "train"],
                                 "trace_paths": traces}
    return resolved


def check_partition(view, resolved):
    """Assert: union of slice cells == body['cells'], no cell twice, trainings covered exactly once."""
    every = [c for r in resolved.values() for c in r["cell_ids"]]
    twice = sorted(c for c, k in Counter(every).items() if k > 1)
    if twice:
        raise SelectorError(f"cells in more than one slice: {twice[:5]}")
    plan_ids = {c["id"] for c in view.cells}
    if set(every) != plan_ids:
        raise SelectorError(f"slices miss {len(plan_ids - set(every))} plan cells and add "
                            f"{len(set(every) - plan_ids)} unknown cells")
    wanted = set(view.body["models"]) if "GLR" in view.body["policies"] else set()
    trains = Counter(n for r in resolved.values() for n in r["train_ns"])
    if set(trains) != wanted or any(k != 1 for k in trains.values()):
        raise SelectorError(f"trainings {dict(trains)} differ from the planned models {sorted(wanted)}")
    return {"cells": len(every), "slices": {k: len(r["cell_ids"]) for k, r in resolved.items()},
            "trainings": sorted(trains)}


def main(argv=None):
    from . import plan_io
    parser = argparse.ArgumentParser(description="resolve M1 slices against a plan (no execution)")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--slices", required=True)
    parser.add_argument("--slice", dest="slice_id")
    args = parser.parse_args(argv)
    view = plan_io.load_readonly(args.plan)
    resolved = resolve_all(view, load_slices(args.slices))
    if args.slice_id:
        print(json.dumps(resolved[args.slice_id], indent=1, sort_keys=True))
    else:
        print(json.dumps({k: {"counted": r["counted"], "cells": len(r["cell_ids"]), "train": r["train_ns"],
                              "traces": len(r["trace_paths"])} for k, r in resolved.items()}, indent=1))
        print(json.dumps(check_partition(view, resolved), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
