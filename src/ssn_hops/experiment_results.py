"""Aggregate saved user-run evidence, never manufacture simulation measurements."""
from collections import Counter, defaultdict
from copy import deepcopy
import math
from pathlib import Path
from statistics import mean, median, stdev
from .config import content_hash, from_dict
from .experiment_io import (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA, NATIVE_POLICY_NAME,
                            NATIVE_RESULT_SCHEMA, digest, inside, native_transport_check,
                            read, schema_guard, single_run_native_reference, source_hashes,
                            validate_plan, write)
from .sim_config import from_sim_dict
from .traffic import read_trace

SUMMARY_SCHEMA = "ssn-experiment-summary-v2"
NATIVE_SUMMARY_SCHEMA = "ssn-native-exhaustive-experiment-summary-v1"
SCIENTIFIC_CONTRACT = {
    "path": "Repo_Orchestrator_2/tasks/T011-S02-native-results.md",
    "commit": "c160b0d24c9a423f93e35fd68daa2777b70c8cae",
    "blob": "789c5a4b1baf0ad37d19577448ad66f3c62fa844",
    "step": "R3/A10/S02B2B",
}
NATIVE_COUNTERS = (
    "policy_calls", "completed_searches", "complete_route_searches",
    "complete_no_route_searches", "complete_zero_hop_searches",
    "incomplete_searches", "incomplete_max_nodes_searches",
    "incomplete_max_expansions_searches", "invalid_input_calls",
    "completed_prefix_entries", "incomplete_prefix_entries", "total_prefix_entries",
    "completed_destination_paths",
)
FIELDS = {"delivered_mean_delay_s": "seconds; delivered packets only",
          "failure_fraction": "unique terminal failed/generated",
          "pending_fraction": "right-censored pending/generated",
          "nondelivery_fraction": "(failed+pending)/generated",
          "goodput_bits_s": "bits/second over observation window",
          "route_seconds_per_call": "CPU wall seconds/choose call; includes inference misses",
          "simulation_seconds": "CPU wall seconds for entire simulator.run"}


def close(actual, expected, label):
    if expected is None:
        if actual is not None:
            raise ValueError(f"{label}: expected JSON null")
    elif (isinstance(actual, bool) or not isinstance(actual, (int, float))
          or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)):
        raise ValueError(f"{label}: inconsistent numerical accounting")


def count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}: expected nonnegative integer")
    return value


def describe(values):
    present = [v for v in values if v is not None]
    for value in present:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("non-finite summary input")
    n = len(present)
    sd = stdev(present) if n > 1 else None
    return {"n_total": len(values), "n_nonnull": n, "n_null": len(values) - n,
            "mean": mean(present) if n else None, "sample_sd": sd,
            "se_of_mean": sd / math.sqrt(n) if sd is not None else None}


def verify_accounting(cfg, records, rows, metrics, timing, events):
    if not isinstance(rows, list) or len(rows) != len(records):
        raise ValueError("packet table/traffic count mismatch")
    by_id = {r.packet_id: r for r in records}
    if len({r["packet_id"] for r in rows}) != len(rows) or {r["packet_id"] for r in rows} != set(by_id):
        raise ValueError("packet IDs are not a bijection with traffic")
    outcomes = Counter()
    reasons = Counter()
    delays = []
    admitted = rejected = active = 0
    row_by_id = {}
    for row in rows:
        source = by_id[row["packet_id"]]
        row_by_id[source.packet_id] = row
        for key in ("created_tick", "source", "destination", "size_bytes"):
            if row[key] != getattr(source, key):
                raise ValueError("packet table differs from paired traffic")
        if row["expiry_tick"] != source.created_tick + cfg.ttl_ticks:
            raise ValueError("packet TTL accounting mismatch")
        status = row["status"]
        if status not in ("delivered", "failed", "pending") or type(row["admitted"]) is not bool:
            raise ValueError("invalid packet outcome/admission flag")
        outcomes[status] += 1
        admitted += int(row["admitted"])
        if row["active_receiver"] is not None:
            if status != "pending":
                raise ValueError("terminal packet has an active transfer")
            active += 1
        if status == "pending":
            if row["terminal_tick"] is not None or row["terminal_reason"] is not None or not row["admitted"]:
                raise ValueError("pending packet incorrectly terminal or rejected")
            close(row["delay_s"], None, "pending delay")
        else:
            tick = count(row["terminal_tick"], "terminal tick")
            if not source.created_tick <= tick <= cfg.horizon_tick:
                raise ValueError("terminal tick outside packet observation")
            if not isinstance(row["terminal_reason"], str):
                raise ValueError("missing terminal reason")
            reasons[row["terminal_reason"]] += 1
            if status == "delivered":
                if row["terminal_reason"] != "delivered" or not row["admitted"] or tick > row["expiry_tick"]:
                    raise ValueError("invalid delivered outcome")
                delay = (tick - source.created_tick) * cfg.tick_s
                close(row["delay_s"], delay, "packet delay")
                delays.append(delay)
            else:
                close(row["delay_s"], None, "failed delay")
                if not row["admitted"]:
                    if row["terminal_reason"] not in ("packet_oversize", "injection_buffer"):
                        raise ValueError("invalid rejected injection reason")
                    rejected += 1
    generated = len(records)
    expected_counts = {"generated": generated, "admitted": admitted, "injection_rejected": rejected,
                       "delivered": outcomes["delivered"], "failed": outcomes["failed"],
                       "pending": outcomes["pending"], "delivered_delay_denominator": len(delays)}
    for key, expected in expected_counts.items():
        if count(metrics[key], key) != expected:
            raise ValueError(f"metric count mismatch: {key}")
    if admitted + rejected != generated or metrics["conservation_checked"] is not True:
        raise ValueError("injection/conservation assertion mismatch")
    for key, numerator in (("failure_fraction", outcomes["failed"]), ("pending_fraction", outcomes["pending"]),
                           ("nondelivery_fraction", outcomes["failed"] + outcomes["pending"]),
                           ("delivered_fraction", outcomes["delivered"])):
        close(metrics[key], numerator / generated if generated else None, key)
    close(metrics["delivered_mean_delay_s"], mean(delays) if delays else None, "mean delivered delay")
    close(metrics["delivered_median_delay_s"], median(delays) if delays else None, "median delivered delay")
    delivered_bytes = sum(r["size_bytes"] for r in rows if r["status"] == "delivered")
    if count(metrics["delivered_bytes"], "delivered bytes") != delivered_bytes:
        raise ValueError("delivered byte count mismatch")
    close(metrics["observation_duration_s"], cfg.observation_end_s, "observation window")
    close(metrics["goodput_bits_s"], 8 * delivered_bytes / cfg.observation_end_s, "goodput")
    if metrics["terminal_reason_counts"] != dict(reasons):
        raise ValueError("terminal reason count mismatch")
    event_counts = Counter()
    event_ids = defaultdict(list)
    abort_reasons = Counter()
    completed_bytes = 0
    for event in events:
        pid = event["packet_id"]
        if pid not in row_by_id:
            raise ValueError("event refers to unknown traffic ID")
        tick = count(event["tick"], "event tick")
        if tick > cfg.horizon_tick:
            raise ValueError("event outside observation")
        close(event["time_s"], tick * cfg.tick_s, "event seconds")
        kind = event["kind"]
        event_counts[kind] += 1
        event_ids[kind].append(pid)
        if kind == "terminal":
            row = row_by_id[pid]
            if (event["tick"] != row["terminal_tick"] or event["status"] != row["status"]
                    or event["reason"] != row["terminal_reason"]):
                raise ValueError("terminal event differs from table")
        if kind == "transfer_aborted":
            abort_reasons[event["reason"]] += 1
        if kind == "hop_completed":
            completed_bytes += row_by_id[pid]["size_bytes"]
    terminal_ids = {r["packet_id"] for r in rows if r["status"] != "pending"}
    for kind, expected_ids in (("generated", set(by_id)), ("terminal", terminal_ids),
                               ("admitted", {r["packet_id"] for r in rows if r["admitted"]})):
        if len(event_ids[kind]) != len(set(event_ids[kind])) or set(event_ids[kind]) != expected_ids:
            raise ValueError(f"{kind} event ledger mismatch")
    counters = metrics["transfer_and_route_counts"]
    for key, expected in (("admitted", admitted), ("injection_rejected", rejected),
                          ("started_transfers", event_counts["transfer_started"]),
                          ("aborted_transfers", event_counts["transfer_aborted"]),
                          ("cancelled_transfers", event_counts["transfer_cancelled"]),
                          ("completed_hops", event_counts["hop_completed"]),
                          ("completed_hop_bytes", completed_bytes)):
        if count(counters[key], key) != expected:
            raise ValueError(f"event/counter mismatch: {key}")
    if counters["started_transfers"] != (counters["aborted_transfers"] + counters["cancelled_transfers"]
                                         + counters["completed_hops"] + active):
        raise ValueError("transfer conservation mismatch")
    if metrics["abort_reason_counts"] != dict(abort_reasons):
        raise ValueError("abort reason count mismatch")
    calls = count(timing["route_calls"], "route calls")
    if calls != count(counters["route_calls"], "metric route calls") or timing["supported_device"] != "cpu":
        raise ValueError("CPU route timing count mismatch")
    for key in ("route_seconds", "simulation_seconds", "topology_snapshot_seconds"):
        value = timing[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid saved CPU timing")
    close(timing["route_seconds_per_call"], timing["route_seconds"] / calls if calls else None, "per-call CPU time")
    return {"generated": generated, "delivered": len(delays), "failed": outcomes["failed"],
            "pending": outcomes["pending"], "delay_sum_s": sum(delays), "route_calls": calls,
            "route_seconds": timing["route_seconds"], "delivered_bytes": delivered_bytes}


def scientific_plan_guard(plan):
    """Native direct callers share the accepted structural/hash/path guards."""
    schema_guard(plan)
    if plan["schema"] == NATIVE_PLAN_SCHEMA:
        validate_plan(plan)
        if source_hashes() != plan["body"]["source_sha256"]:
            raise ValueError("source files changed since planning; create a fresh plan")


def verify_native_counters(details, native, timing, metrics):
    """Validate saved diagnostics, NOT prove execution of the declared algorithm.

    Definitions: tbr_policy.py at245aa27, blob5a554294. Each returned complete
    core search includes its root prefix; each destination path is an entered
    prefix. A route/zero-hop completion has at least one such destination.
    No graph-dependent exact expansion/path counts are asserted here.
    """
    identity = {key: native[key] for key in
                ("policy_identity", "search_identity", "objective", "max_nodes", "max_expansions")}
    identity.update({
        "algorithm": "exhaustive admissible simple paths per policy call; independently specified, not author code or timing",
        "budget_scope": "independent safety controls; not author settings",
    })
    if not isinstance(details, dict) or set(details) != set(identity) | set(NATIVE_COUNTERS):
        raise ValueError("native diagnostic fields mismatch")
    for key, expected in identity.items():
        if content_hash(details[key]) != content_hash(expected):
            raise ValueError(f"native diagnostic identity/limits mismatch: {key}")
    values = {key: count(details[key], "native " + key) for key in NATIVE_COUNTERS}
    completed = values["completed_searches"]
    incomplete = values["incomplete_searches"]
    if completed != sum(values[k] for k in
                        ("complete_route_searches", "complete_no_route_searches", "complete_zero_hop_searches")):
        raise ValueError("native completed-search algebra mismatch")
    if values["policy_calls"] != completed + incomplete + values["invalid_input_calls"]:
        raise ValueError("native policy-call algebra mismatch")
    if incomplete != values["incomplete_max_nodes_searches"] + values["incomplete_max_expansions_searches"]:
        raise ValueError("native incomplete-search algebra mismatch")
    if values["total_prefix_entries"] != values["completed_prefix_entries"] + values["incomplete_prefix_entries"]:
        raise ValueError("native prefix algebra mismatch")
    for calls in (timing["route_calls"], metrics["transfer_and_route_counts"]["route_calls"]):
        if values["policy_calls"] != count(calls, "saved route calls"):
            raise ValueError("native policy/route-call count mismatch")
    if any(values[k] for k in ("incomplete_searches", "incomplete_max_nodes_searches",
                              "incomplete_max_expansions_searches", "invalid_input_calls", "incomplete_prefix_entries")):
        raise ValueError("successful native result contains incomplete/invalid search work")
    prefixes = values["completed_prefix_entries"]
    paths = values["completed_destination_paths"]
    if not completed <= prefixes <= completed * native["max_expansions"]:
        raise ValueError("native completed prefix bounds mismatch")
    if not values["complete_route_searches"] + values["complete_zero_hop_searches"] <= paths <= prefixes:
        raise ValueError("native destination path bounds mismatch")
    return deepcopy(details)


def verify_cell(plan, cell, scenario, model_records):
    scientific_plan_guard(plan)
    if plan["schema"] == NATIVE_PLAN_SCHEMA:
        try:
            if (not any(content_hash(cell) == content_hash(c) for c in plan["body"]["cells"])
                    or not any(content_hash(scenario) == content_hash(s) for s in plan["body"]["scenarios"])
                    or cell["scenario"] != scenario["id"]):
                raise ValueError("cell/scenario not in the native plan")
            return _verify_cell(plan, cell, scenario, model_records)
        except (KeyError, TypeError, AttributeError, OverflowError, OSError) as exc:
            raise ValueError("malformed/missing completed native-plan cell artifact") from exc
    return _verify_cell(plan, cell, scenario, model_records)


def _verify_cell(plan, cell, scenario, model_records):
    native_plan = plan["schema"] == NATIVE_PLAN_SCHEMA
    native_cell = native_plan and cell["policy"] == NATIVE_POLICY_NAME
    root = Path(plan["body"]["root"])
    output = inside(root, cell["out"])
    status_path = root / "logs" / (cell["id"] + ".status.json")
    has_complete = (output / "complete.json").exists()
    has_status = status_path.exists()
    # Preserve legacy missing/failed behavior. Native completed artifacts are
    # inspected even if their status is absent/failed, never hidden by partial.
    if not native_plan and (not has_complete or not has_status):
        return None
    status = read(status_path) if has_status else None
    if native_plan and has_status:
        required = {"id", "argv", "cwd", "revision", "plan_sha256", "exit_code", "exception"}
        if not isinstance(status, dict) or not required <= set(status):
            raise ValueError("missing native-plan job status fields")
        argv = status["argv"]
        if (not isinstance(argv, list) or not argv
                or any(not isinstance(arg, str) or not arg for arg in argv)
                or not isinstance(status["cwd"], str) or not status["cwd"]):
            raise ValueError("invalid native-plan job argv/cwd")
        exit_code = status["exit_code"]
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError("invalid native-plan job exit code")
        if status["exception"] is not None and not isinstance(status["exception"], str):
            raise ValueError("invalid native-plan job exception")
    successful = (status is not None and status.get("exit_code") == 0
                  and status.get("exception") is None)
    if not native_plan and not successful:
        return None
    if status is not None:
        if status["plan_sha256"] != plan["sha256"] or status["revision"] != plan["body"]["revision"]:
            raise ValueError("cell status belongs to another plan/revision")
        if status["id"] != cell["id"] or status["argv"][1:] != cell["command"][1:]:
            raise ValueError("status command differs from planned cell")
        if successful:
            for suffix, expected in status["log_sha256"].items():
                if suffix not in (".stdout.txt", ".stderr.txt") or digest(root / "logs" / (cell["id"] + suffix)) != expected:
                    raise ValueError("cell stdout/stderr hash mismatch")
            if set(status["log_sha256"]) != {".stdout.txt", ".stderr.txt"}:
                raise ValueError("missing execution log hashes")
    if not has_complete:
        return None
    complete = read(output / "complete.json")
    if complete.get("simulation_finished") is not True or complete["result_sha256"] != digest(output / "result.json"):
        raise ValueError("simulation completion/hash mismatch")
    if native_cell:
        native_transport_check(plan, cell, scenario)
    result = read(output / "result.json")
    expected_schema = NATIVE_RESULT_SCHEMA if native_cell else "ssn-simulation-result-v2"
    if result["schema"] != expected_schema or result["policy"] != cell["policy"]:
        raise ValueError("result schema/policy mismatch; v1 results are not corrected R3 evidence")
    if result["declared_checkout_revision"] != plan["body"]["revision"]:
        raise ValueError("result revision differs from suite")
    expected_files = {"config.json", "traffic.json", "provenance.json", "packets.json", "events.jsonl"}
    if set(result["output_sha256"]) != expected_files:
        raise ValueError("incomplete result artifact hash map")
    for filename, expected in result["output_sha256"].items():
        if digest(output / filename) != expected:
            raise ValueError(f"result artifact hash mismatch: {filename}")
    cfg = from_sim_dict(read(output / "config.json"))
    if cfg.to_dict() != scenario["config"] or cfg.sha256 != scenario["config_sha256"] or result["config_sha256"] != cfg.sha256:
        raise ValueError("result configuration differs from planned cell")
    origin = read(output / "provenance.json")
    if (origin["declared_checkout_revision"] != plan["body"]["revision"]
            or origin["source_sha256"] != plan["body"]["source_sha256"]):
        raise ValueError("result source/revision provenance mismatch")
    trace = read(inside(root, scenario["trace_path"]))
    if read(output / "traffic.json") != trace or result["traffic_sha256"] != trace["sha256"]:
        raise ValueError("result did not use the paired suite traffic")
    records = read_trace(trace, cfg)
    expected_inputs = {str(root / cell["config_path"]): digest(root / cell["config_path"]),
                       str(root / scenario["trace_path"]): digest(root / scenario["trace_path"])}
    if origin["input_file_sha256"] != expected_inputs:
        raise ValueError("original config/trace input hashes differ")
    checkpoint = result["timing"]["checkpoint"]
    if cell["policy"] == "GLR":
        model = model_records[str(cfg.orbit.n)]
        expected = {"sha256": model["checkpoint_sha256"], "training_config_sha256": model["training_config_sha256"],
                    "training_revision": model["training_revision"], "epoch": model["epoch"],
                    "feature_spec": model["feature_spec"]}
        if checkpoint != expected or result["policy_details"].get("feature_spec") != model["feature_spec"]:
            raise ValueError("GLR checkpoint/input identity differs from preflight")
    elif checkpoint is not None:
        raise ValueError("baseline claims a GLR checkpoint")
    packets = read(output / "packets.json")
    if set(packets) != {"schema", "rows"} or packets["schema"] != "ssn-packet-table-v1":
        raise ValueError("packet table schema mismatch")
    with (output / "events.jsonl").open(encoding="utf-8") as handle:
        import json
        events = [json.loads(line) for line in handle]
    totals = verify_accounting(cfg, records, packets["rows"], result["metrics"], result["timing"], events)
    diagnostics = (verify_native_counters(result["policy_details"], plan["body"]["native_reference"],
                                         result["timing"], result["metrics"]) if native_cell else None)
    if native_plan and not successful:
        return None
    values = {key: result["metrics"][key] for key in FIELDS if key not in ("route_seconds_per_call", "simulation_seconds")}
    values.update({key: result["timing"][key] for key in ("route_seconds_per_call", "simulation_seconds")})
    checked = {"values": values, "totals": totals, "result_sha256": complete["result_sha256"],
               "traffic_sha256": trace["sha256"], "cell": cell["id"]}
    if native_plan:
        checked.update({"output_sha256": deepcopy(result["output_sha256"]),
                        "log_sha256": deepcopy(status["log_sha256"]),
                        "native_counters": diagnostics})
    return checked


def verify_models(plan):
    if "GLR" not in plan["body"]["policies"]:
        return {}
    root = Path(plan["body"]["root"])
    preflight = read(root / "model_preflight.json")
    if preflight["plan_sha256"] != plan["sha256"] or set(preflight["models"]) != set(plan["body"]["models"]):
        raise ValueError("model preflight plan/mapping mismatch")
    from .experiments import check_model
    for n, model in preflight["models"].items():
        item = plan["body"]["models"][n]
        if model["run"] != item["run"] or digest(Path(item["run"]) / "best.pt") != model["checkpoint_sha256"]:
            raise ValueError("checkpoint missing/changed since preflight")
        cfg = check_model(read(Path(item["run"]) / "config.json"),
                          [s["config"] for s in plan["body"]["scenarios"] if str(s["config"]["orbit"]["n"]) == n],
                          from_dict(item["config"]).model)
        if cfg.sha256 != model["training_config_sha256"]:
            raise ValueError("training config hash differs from preflight")
        if model.get("feature_spec") != cfg.model.feature_spec or item["feature_spec"] != cfg.model.feature_spec:
            raise ValueError("model feature identity differs from plan/preflight")
    return preflight["models"]


def summarize_group(matched, policies, reference):
    """Only complete policy-matched repetitions enter ANY group estimate."""
    results = {}
    differences = {}
    for policy in policies:
        runs = [item[policy] for item in matched]
        equal = {key: describe([r["values"][key] for r in runs]) for key in FIELDS}
        totals = {key: sum(r["totals"][key] for r in runs)
                  for key in ("generated", "delivered", "failed", "pending", "delay_sum_s", "route_calls", "route_seconds", "delivered_bytes")}
        g, d, calls = totals["generated"], totals["delivered"], totals["route_calls"]
        pooled = {**totals, "delivered_mean_delay_s": totals["delay_sum_s"] / d if d else None,
                  "failure_fraction": totals["failed"] / g if g else None,
                  "pending_fraction": totals["pending"] / g if g else None,
                  "nondelivery_fraction": (totals["failed"] + totals["pending"]) / g if g else None,
                  "route_seconds_per_call": totals["route_seconds"] / calls if calls else None}
        results[policy] = {"equal_replicate": equal, "pooled_packet_and_call": pooled}
        if policy != reference:
            differences[policy] = {}
            for key in FIELDS:
                values = []
                for item in matched:
                    left, right = item[policy]["values"][key], item[reference]["values"][key]
                    values.append(left - right if left is not None and right is not None else None)
                differences[policy][key] = describe(values)
    return results, differences


def summarize_scoped_group(present, policies, reference):
    """Plans with scenario['policies'] (policy_scope): per-policy matching, NEVER used for unscoped plans.

    `present` holds one dict per scenario of the group, {policy: verified cell record}, containing
    exactly the declared cells that are verified (undeclared or unverified policies are absent).
    A policy's estimates use the scenarios where that policy is present; paired differences
    (policy minus reference) use the scenarios where both are present. The arithmetic is the
    unchanged summarize_group arithmetic applied to complete sub-lists, so a policy without any
    verified cell gets n_total 0 and null estimates, never zeros.
    """
    results = {}
    differences = {}
    for policy in policies:
        own = [item for item in present if policy in item]
        results[policy] = summarize_group(own, [policy], policy)[0][policy]
        if policy != reference:
            both = [item for item in own if reference in item]
            differences[policy] = summarize_group(both, [policy], reference)[1][policy]
    return results, differences


def native_completion_marker(plan):
    path = Path(plan["body"]["root"]) / "execution_complete.json"
    if not path.exists():
        return False, None
    marker = read(path)
    expected = {"schema": "ssn-native-experiment-transport-complete-v1",
                "transport_finished": True, "runs": len(plan["body"]["cells"]),
                "plan_sha256": plan["sha256"], "aggregation_supported": False,
                "plots_supported": False,
                "scope": "all planned child artifacts transported; scientific verification/aggregation NOT performed"}
    if not isinstance(marker, dict) or type(marker.get("transport_finished")) is not bool:
        raise ValueError("native transport completion marker malformed")
    # An explicit false flag is incomplete, not success; all other fields remain exact.
    expected["transport_finished"] = marker["transport_finished"]
    if content_hash(marker) != content_hash(expected):
        raise ValueError("native transport completion marker differs from plan/scope")
    return marker["transport_finished"], marker


def scoped_declarations(body, scenarios):
    """None when no scenario carries 'policies' (the legacy plan: old behaviour, nothing checked here).

    Otherwise {scenario id: declared policy list}. Plans are all-or-none, every list must be a
    nonempty list of distinct policies of body['policies'], and body['cells'] must be exactly the
    declared (scenario, policy) pairs (direct callers of aggregate_plan skip validate_plan).
    """
    carrying = [s for s in scenarios.values() if "policies" in s]
    if not carrying:
        return None
    if len(carrying) != len(scenarios):
        raise ValueError("mixed scoped/unscoped scenarios in plan")
    declared = {}
    for scenario in scenarios.values():
        listed = scenario["policies"]
        if (not isinstance(listed, list) or not listed
                or any(not isinstance(policy, str) for policy in listed)
                or len(set(listed)) != len(listed)
                or any(policy not in body["policies"] for policy in listed)):
            raise ValueError("invalid scenario policy declaration")
        declared[scenario["id"]] = list(listed)
    pairs = [(cell["scenario"], cell["policy"]) for cell in body["cells"]]
    expected = {(sid, policy) for sid, listed in declared.items() for policy in listed}
    if len(pairs) != len(expected) or set(pairs) != expected:
        raise ValueError("plan cells differ from declared scenario policies")
    return declared


def aggregate_plan(plan, output, allow_partial=False, reference="TBR_style_hop_oracle"):
    scientific_plan_guard(plan)
    native_plan = plan["schema"] == NATIVE_PLAN_SCHEMA
    body = plan["body"]
    if reference not in body["policies"]:
        raise ValueError("reference policy was not planned")
    root = Path(body["root"])
    model_records = verify_models(plan)
    scenarios = {s["id"]: s for s in body["scenarios"]}
    declared = scoped_declarations(body, scenarios)
    verified = defaultdict(dict)
    missing = []
    evidence = {}
    exclusions = {}
    for cell in body["cells"]:
        # Native plan has already been validated once above; public verify_cell
        # performs the same validation for direct callers.
        try:
            value = _verify_cell(plan, cell, scenarios[cell["scenario"]], model_records)
        except (KeyError, TypeError, AttributeError, OverflowError, OSError) as exc:
            if not native_plan:
                raise
            raise ValueError("malformed/missing completed native-plan cell artifact") from exc
        if value is None:
            missing.append(cell["id"])
            if native_plan:
                status_path = root / "logs" / (cell["id"] + ".status.json")
                exclusions[cell["id"]] = (
                    "missing job status" if not status_path.exists() else
                    "failed job" if read(status_path).get("exit_code") != 0 or read(status_path).get("exception") is not None else
                    "missing completion artifact")
        else:
            verified[cell["scenario"]][cell["policy"]] = value
            evidence[cell["id"]] = {"result_sha256": value["result_sha256"], "traffic_sha256": value["traffic_sha256"]}
            if native_plan:
                evidence[cell["id"]].update({key: value[key] for key in
                                             ("output_sha256", "log_sha256", "native_counters")})
    completion_path = root / "execution_complete.json"
    finished = False
    marker = None
    if native_plan:
        finished, marker = native_completion_marker(plan)
    elif completion_path.exists():
        marker = read(completion_path)
        if marker.get("suite_finished") is not True or marker["plan_sha256"] != plan["sha256"] or marker["runs"] != len(body["cells"]):
            raise ValueError("suite completion marker differs from plan")
        finished = True
    complete = not missing and finished
    if not complete and not allow_partial:
        raise ValueError(f"suite incomplete: {len(missing)} missing/failed cells; completion marker={finished}")
    buckets = defaultdict(list)
    for scenario in scenarios.values():
        for member in scenario["memberships"]:
            buckets[(member["grid"], scenario["variant"], member["axis"], member["x"])].append(scenario)
    groups = []
    for (grid, variant, axis, x), items in sorted(buckets.items()):
        matched = []
        included = []
        excluded = []
        present = []
        controls = set()
        for scenario in items:
            control = deepcopy(scenario["config"])
            for seed in ("phase_seed", "traffic_seed", "failure_seed"):
                control.pop(seed)
            controls.add(content_hash(control))
            if declared is not None:
                present.append(verified[scenario["id"]])
            needed = body["policies"] if declared is None else declared[scenario["id"]]
            if set(verified[scenario["id"]]) == set(needed):
                matched.append(verified[scenario["id"]])
                included.append(scenario["seeds"])
            else:
                excluded.append(scenario["seeds"])
        if len(controls) != 1:
            raise ValueError("unmatched tick/rate/load/orbit/control variants in group")
        if declared is None:
            policies, paired = summarize_group(matched, body["policies"], reference)
        else:
            policies, paired = summarize_scoped_group(present, body["policies"], reference)
        cfg = items[0]["config"]
        groups.append({"grid": grid, "variant": variant, "axis": axis, "x": x,
                       "control_sha256": next(iter(controls)), "planned_repetitions": len(items),
                       "matched_repetitions": len(matched), "included_seed_tuples": included,
                       "excluded_seed_tuples": excluded,
                       "controls": {"tick_s": cfg["tick_s"], "rate_bytes_s": cfg["rate_bytes_s"],
                                    "arrival_rate_packets_s": 1 / cfg["arrival_interval_s"],
                                    "traffic_end_s": cfg["traffic_end_s"], "observation_end_s": cfg["observation_end_s"],
                                    "n": cfg["orbit"]["n"], "planes": cfg["orbit"]["planes"],
                                    "failure_probability": cfg["failure_probability"]},
                       "policies": policies, "paired_policy_minus_reference": paired})
        if declared is not None:
            groups[-1]["policy_cells"] = {
                policy: {"planned": sum(policy in declared[s["id"]] for s in items),
                         "verified": sum(policy in verified[s["id"]] for s in items)}
                for policy in body["policies"]}
    document = {"schema": SUMMARY_SCHEMA, "label": "RECONSTRUCTION / NOT AUTHORS' RESULTS",
                "complete": complete, "mode": body["mode"], "plan_sha256": plan["sha256"],
                "declared_checkout_revision": body["revision"], "source_sha256": body["source_sha256"],
                "model_feature_specs": {n: m["feature_spec"] for n, m in model_records.items()},
                "reference_policy": reference, "policy_names": body["policies"], "field_units": FIELDS,
                "missing_or_failed_cells": missing, "suite_completion_marker_present": finished,
                "artifact_evidence": evidence, "groups": groups,
                "statistics": "Equal-replicate means, sample SD (ddof=1), SE=SD/sqrt(non-null n); no confidence interval. Paired differences only identical scenario/seed. No-delivery delay is null; null delay pairs excluded with counts. Pooled packet delays use delivered denominator. Pending packets right-censored, never treated as zero-delay deliveries.",
                "timing_warning": "CPU wall seconds per route call and whole-run seconds are separate. TBR_style_hop_oracle is BFS, NON-COMPARABLE to paper brute-force Fig.5.",
                "authentication_limit": "Hashes/revisions detect accidental mismatch, not forgery. Only genuine trusted user execution supports empirical claims."}
    if declared is not None:
        suite = body.get("suite")
        document["policy_scope"] = {
            "suite_policy_scope": deepcopy(suite.get("policy_scope")) if isinstance(suite, dict) else None,
            "scenario_policies_sha256": content_hash([[sid, listed] for sid, listed in declared.items()]),
            "declared_cells_by_policy": {policy: sum(policy in listed for listed in declared.values())
                                         for policy in body["policies"]},
            "planned_cells": len(body["cells"]), "verified_cells": len(evidence),
            "absent_by_design_cells": len(declared) * len(body["policies"]) - len(body["cells"]),
            "absent_by_design_note": "Cells of policies that are not declared at a scenario do not exist in the plan: they are absent by design, are NOT missing, and never appear in missing_or_failed_cells.",
            "completeness_note": "complete requires every DECLARED cell verified and the completion marker; a summary of a plan whose declared cells are not all executed is PARTIAL by decision.",
            "matched_repetitions_meaning": "Per group: number of scenarios in which EVERY policy declared at that scenario is verified (equals planned_repetitions when all declared cells are verified); a group-level count, not a per-policy sample size. Per-policy sample sizes: policies[p].equal_replicate[*].n_total and groups[*].policy_cells[p].verified; paired sample sizes: paired_policy_minus_reference[p][*].n_total.",
            "statistics_note": "Policy estimates use the scenarios where the policy is declared and verified; paired differences (policy minus reference) use the scenarios where both are declared and verified; a policy without any verified cell in a group has n_total 0 and null estimates, never zeros."}
    if native_plan:
        document.pop("suite_completion_marker_present")
        document.update({
            "schema": NATIVE_SUMMARY_SCHEMA,
            "producer_plan_schema": plan["schema"],
            "producer_native_reference": deepcopy(body["native_reference"]),
            "producer_single_run_reference": single_run_native_reference(body["native_reference"]),
            "transport_completion_marker": marker,
            "transport_completion_marker_present": marker is not None,
            "transport_finished": finished,
            "scientifically_verified_cells": len(evidence), "planned_cells": len(body["cells"]),
            "excluded_cells": exclusions,
            "scientific_consumer": {"contract": dict(SCIENTIFIC_CONTRACT),
                                    "aggregation_supported": True, "plots_supported": False,
                                    "scope": "strict saved-artifact scientific verification and complete planned-policy paired aggregation; plots unsupported",
                                    "counter_evidence": "verified saved native diagnostic types, identities, budgets, algebra and bounds; NOT proof of algorithm execution",
                                    "producer_scope_interpretation": "original single-run and transport declarations retained unchanged as historical layer claims; not retroactively relabeled"},
            "timing_warning": "TBR_style_hop_oracle is a BFS practical alternative, NON-COMPARABLE to paper brute-force Fig.5. Native timing is whole choose-call CPU wall seconds including adapter/core validation/search/counters, excluding context/masks; not pure-core time. Whole simulation time is separate. Author traversal and Fig.5 cost-axis unit are unknown; no author-cost equality is claimed.",
        })
    write(output, document)
    return {"summary": str(output), "sha256": digest(output), "complete": complete,
            "groups": len(groups), "missing_or_failed_cells": len(missing)}
