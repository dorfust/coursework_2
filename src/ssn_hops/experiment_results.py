"""Aggregate saved user-run evidence, never manufacture simulation measurements."""
from collections import Counter, defaultdict
from copy import deepcopy
import math
from pathlib import Path
from statistics import mean, median, stdev
from .config import content_hash, from_dict
from .experiment_io import (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA, NATIVE_POLICY_NAME,
                            NATIVE_RESULT_SCHEMA, ENUM_POLICY_NAME, digest, inside,
                            native_transport_check, read, schema_guard,
                            single_run_native_reference, source_hashes, validate_plan, write)
from .sim_config import from_sim_dict
from .traffic import read_trace

SUMMARY_SCHEMA = "ssn-experiment-summary-v2"
NATIVE_SUMMARY_SCHEMA = "ssn-native-exhaustive-experiment-summary-v1"
# Fixed text: copied into every native summary as scientific_consumer.contract. experiment_plots rebuilds the
# scientific_consumer record from this constant and from copies of its text strings and compares the two.
# The same pairing exists for the transport marker record (native_completion_marker here, expected_marker there),
# the summary label (LABEL there), the unit strings of FIELDS and the five result file names (also in
# experiment_io.native_transport_check). If the two copies differ, plotting a native summary is refused.
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
# T125: integer counters of TBR_enumeration.stats() (see tbr_enum.py); the other keys are
# identity strings, the two budgets, completeness_share (float or None) and cell_budget_exhausted.
ENUM_COUNTERS = (
    "policy_calls", "complete_route", "complete_no_route", "complete_zero_hop",
    "incomplete_call_budget", "skipped_after_cell_budget", "total_expansions",
    "complete_expansions_sum", "complete_expansions_max", "incomplete_expansions_sum",
    "max_depth_completed",
)
# The six text keys of the saved enumeration diagnostics. verify_enum_counters requires each to be a non-empty
# string; search_identity and objective are also compared with the plan options.
ENUM_STRING_KEYS = ("policy_identity", "search_identity", "objective", "algorithm",
                    "budget_scope", "incomplete_rule")
# The seven per-run values that are aggregated, with their units. Fractions are ratios of counts (for example
# failed / generated), not percent; delays and times are in seconds; goodput is in bits per second. _verify_cell
# takes the values from result["metrics"], except route_seconds_per_call and simulation_seconds, which come from
# result["timing"]. delivered_fraction and delivered_median_delay_s are checked in verify_accounting but not
# aggregated. The dict is copied into summary["field_units"]; experiment_plots compares that copy with this dict
# for native summaries, so a changed string makes a native summary written earlier fail that comparison.
FIELDS = {"delivered_mean_delay_s": "seconds; delivered packets only",
          "failure_fraction": "unique terminal failed/generated",
          "pending_fraction": "right-censored pending/generated",
          "nondelivery_fraction": "(failed+pending)/generated",
          "goodput_bits_s": "bits/second over observation window",
          "route_seconds_per_call": "CPU wall seconds/choose call; includes inference misses",
          "simulation_seconds": "CPU wall seconds for entire simulator.run"}


# close(actual, expected, label): if expected is None, actual must be None; otherwise actual must be a finite int
# or float (not bool) within math.isclose with rel_tol = abs_tol = 1e-10 of expected. It compares saved numbers
# with recomputed ones; it is not an equality test.
# count(value, label): returns value if it is an int (a bool is refused, because the test is type(value) is int)
# and not negative.
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
    """Statistics of one list of per-repetition values; None means undefined for that repetition.

    n_total = len(values); n_nonnull and n_null count the values that are and are not None. mean is the
    arithmetic mean of the non-null values. sample_sd is statistics.stdev of the non-null values (the summary
    text calls it sample SD, ddof=1) and exists only for two or more of them. se_of_mean = sample_sd /
    sqrt(n_nonnull): one standard error, no confidence interval. With one non-null value sample_sd and
    se_of_mean are None; with none, mean is None as well. A None is never replaced by 0. ValueError for a
    non-null value that is a bool, not an int or float, or not finite.
    """
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
    """Cross-check one cell's saved packet table, events, metrics and timing against its paired traffic records.

    ValueError on the first mismatch. Counts are compared exactly; real numbers go through close() (tolerance
    1e-10). Seconds are ticks * cfg.tick_s; goodput is 8 * delivered_bytes / cfg.observation_end_s (bits per
    second); fractions are count / generated (None when generated is 0). Steps in order: table rows against the
    traffic records (ids, created_tick, source, destination, size_bytes, expiry_tick = created_tick + cfg.ttl_ticks);
    per-row status (delivered, failed, pending) with its terminal tick, reason, admission and delay rules; metric
    counts, fractions, mean and median delay, delivered bytes, observation window, goodput and terminal_reason_counts;
    the event list against the table and against transfer_and_route_counts (started transfers = aborted + cancelled
    + completed hops + pending packets with an active receiver); timing route calls, supported_device equal to cpu,
    finite non-negative seconds and route_seconds_per_call. Returns the totals that summarize_group pools.
    """
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


# For every plan: schema_guard. A plan with the native schema also gets validate_plan and a comparison of
# source_hashes() (every *.py file of the package folder as it is now) with plan["body"]["source_sha256"]; any
# difference is a ValueError. A plan with the legacy schema gets only schema_guard in this function. _verify_cell
# separately compares the plan's source hashes with the provenance saved by each cell.
def scientific_plan_guard(plan):
    """Native direct callers share the accepted structural/hash/path guards."""
    schema_guard(plan)
    if plan["schema"] == NATIVE_PLAN_SCHEMA:
        validate_plan(plan)
        if source_hashes() != plan["body"]["source_sha256"]:
            raise ValueError("source files changed since planning; create a fresh plan")


# `native` is plan["body"]["native_reference"]. The saved diagnostics must carry exactly the identity keys and
# NATIVE_COUNTERS. Unlike verify_enum_counters, any incomplete or invalid search makes the cell fail here.
# The budget_scope text compared here is "independent safety controls; not author settings"; native_options in
# experiment_io.py builds the same sentence with NOT in capitals. This function compares it with the saved
# diagnostics only.
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


# Compared with the plan options: search_identity, objective, max_call_expansions, max_cell_expansions; policy_identity
# is compared with ENUM_POLICY_NAME. algorithm, budget_scope and incomplete_rule only have to be non-empty strings
# (their text is not compared). max_depth_completed only has to be a non-negative int. cell_budget_exhausted must be
# a bool equal to (total_expansions > max_cell_expansions); completeness_share must match completed / policy_calls
# (compared with close()).
def verify_enum_counters(details, options, timing, metrics):
    """T125: validate the saved TBR_enumeration diagnostics against the plan metadata.

    Checks types, the exact key set, identity strings, the two budgets and the counter algebra
    (see tbr_enum.TBR_enumeration.stats). Incomplete and skipped calls are ALLOWED here (they are
    reported, not errors; contrast verify_native_counters). It does NOT prove that the declared
    algorithm ran. Every incomplete call enters exactly max_call_expansions prefixes.
    """
    if not isinstance(options, dict):
        raise ValueError("TBR_enumeration cell without plan options")
    expected_keys = (set(ENUM_COUNTERS) | set(ENUM_STRING_KEYS)
                     | {"max_call_expansions", "max_cell_expansions", "completeness_share",
                        "cell_budget_exhausted"})
    if not isinstance(details, dict) or set(details) != expected_keys:
        raise ValueError("enumeration diagnostic fields mismatch")
    if details["policy_identity"] != ENUM_POLICY_NAME:
        raise ValueError("enumeration diagnostic policy identity mismatch")
    for key in ("search_identity", "objective"):
        if details[key] != options[key]:
            raise ValueError(f"enumeration diagnostic identity mismatch: {key}")
    for key in ENUM_STRING_KEYS:
        if not isinstance(details[key], str) or not details[key]:
            raise ValueError(f"enumeration diagnostic text missing: {key}")
    max_call = count(details["max_call_expansions"], "enumeration max_call_expansions")
    max_cell = count(details["max_cell_expansions"], "enumeration max_cell_expansions")
    if max_call != options["max_call_expansions"] or max_cell != options["max_cell_expansions"]:
        raise ValueError("enumeration diagnostic budgets differ from the plan")
    values = {key: count(details[key], "enumeration " + key) for key in ENUM_COUNTERS}
    completed = values["complete_route"] + values["complete_no_route"] + values["complete_zero_hop"]
    incomplete = values["incomplete_call_budget"]
    skipped = values["skipped_after_cell_budget"]
    if values["policy_calls"] != completed + incomplete + skipped:
        raise ValueError("enumeration policy-call algebra mismatch")
    for calls in (timing["route_calls"], metrics["transfer_and_route_counts"]["route_calls"]):
        if values["policy_calls"] != count(calls, "saved route calls"):
            raise ValueError("enumeration policy/route-call count mismatch")
    if values["total_expansions"] != values["complete_expansions_sum"] + values["incomplete_expansions_sum"]:
        raise ValueError("enumeration expansion algebra mismatch")
    if values["incomplete_expansions_sum"] != incomplete * max_call:
        raise ValueError("enumeration incomplete calls must enter exactly max_call_expansions prefixes")
    if not completed <= values["complete_expansions_sum"] <= completed * max_call:
        raise ValueError("enumeration completed expansion bounds mismatch")
    if values["complete_expansions_max"] > max_call or (completed and values["complete_expansions_max"] < 1):
        raise ValueError("enumeration per-call maximum mismatch")
    if type(details["cell_budget_exhausted"]) is not bool:
        raise ValueError("enumeration exhaustion flag must be boolean")
    if details["cell_budget_exhausted"] != (values["total_expansions"] > max_cell):
        raise ValueError("enumeration exhaustion flag inconsistent with the cell budget")
    if skipped and not details["cell_budget_exhausted"]:
        raise ValueError("enumeration skipped calls without an exhausted cell budget")
    close(details["completeness_share"], completed / values["policy_calls"] if values["policy_calls"] else None,
          "enumeration completeness share")
    return deepcopy(details)


# Pooled share = completed_calls / policy_calls over all calls of the cells passed in, so each call has weight 1;
# the equal-replicate means of the metrics give each cell (repetition) weight 1. The shares are fractions between
# 0 and 1, None if there is no call; experiment_plots prints the pooled share as percent. completeness_share_per_cell
# keeps the order of `records` and holds the share each cell reported (None for a cell without calls).
# cells_with_exhausted_cell_budget counts the records whose cell_budget_exhausted is true. In aggregate_plan the
# records are the verified diagnostics of the cells that enter the group estimates.
def enumeration_completeness(records):
    """T125: pooled and per-cell completeness of TBR_enumeration over verified diagnostics.

    `records` are verify_enum_counters results (one per cell). A call is 'completed' when its
    search finished (route, no route or zero hop); incomplete and skipped calls are waits.
    """
    calls = sum(r["policy_calls"] for r in records)
    done = sum(r["complete_route"] + r["complete_no_route"] + r["complete_zero_hop"] for r in records)
    return {"cells": len(records), "policy_calls": calls, "completed_calls": done,
            "incomplete_call_budget": sum(r["incomplete_call_budget"] for r in records),
            "skipped_after_cell_budget": sum(r["skipped_after_cell_budget"] for r in records),
            "cells_with_exhausted_cell_budget": sum(1 for r in records if r["cell_budget_exhausted"]),
            "total_expansions": sum(r["total_expansions"] for r in records),
            "completeness_share_pooled": done / calls if calls else None,
            "completeness_share_per_cell": [r["completeness_share"] for r in records],
            "scope": "over the cells of this group that enter the estimates; an incomplete or skipped call is a wait, never a route"}


def verify_cell(plan, cell, scenario, model_records):
    """Verify one cell for a direct caller: return what _verify_cell returns, or raise ValueError.

    scientific_plan_guard runs on every call. For a native plan the cell and the scenario must be members of
    plan["body"] (compared by content hash) and cell["scenario"] must equal scenario["id"]; KeyError, TypeError,
    AttributeError, OverflowError and OSError raised inside _verify_cell are re-raised as ValueError. For a
    legacy plan _verify_cell is called directly and its exceptions are not converted. aggregate_plan calls
    _verify_cell itself, after one scientific_plan_guard call.
    """
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
    """Verify one cell from its saved files: return a record, return None (the cell counts as missing) or raise ValueError.

    Legacy plan: None if <out>/complete.json or logs/<id>.status.json is absent, or if the status shows a job that
    is not successful (exit_code other than 0, or an exception recorded). Native plan: a cell with complete.json is
    inspected whatever its status; None only if complete.json is absent, or if the full check passed and the status
    is absent or not successful. A status must name this plan, revision and cell, and its argv[1:] must equal the
    planned command[1:]; for a successful job the stdout and stderr hashes must match. Then, in order: complete.json
    and result.json hashes, native_transport_check (native policy cells), result schema, policy and revision, the
    five result files and their hashes, config, provenance, traffic and input-file hashes against the plan, the GLR
    checkpoint identity against the preflight (other policies must claim none), verify_accounting,
    verify_native_counters for the native policy and verify_enum_counters for TBR_enumeration. The record has the
    keys values, totals, result_sha256, traffic_sha256 and cell, plus enumeration (TBR_enumeration cells) and
    output_sha256, log_sha256 and native_counters (native plans).
    """
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
    if cell["policy"] == ENUM_POLICY_NAME:
        # T125: incomplete searches are allowed and reported, never an error.
        checked["enumeration"] = verify_enum_counters(result["policy_details"],
                                                      plan["body"].get("tbr_enumeration"),
                                                      result["timing"], result["metrics"])
    if native_plan:
        checked.update({"output_sha256": deepcopy(result["output_sha256"]),
                        "log_sha256": deepcopy(status["log_sha256"]),
                        "native_counters": diagnostics})
    return checked


def verify_models(plan):
    """Return {} if GLR is not among the planned policies; otherwise check the model preflight and return its models mapping.

    Reads <root>/model_preflight.json: its plan_sha256 must equal the plan hash and its set of model sizes must
    equal the plan's. For each size, <run>/best.pt is hashed (not loaded) and must match the preflight checkpoint
    hash; check_model (imported inside this function from experiments.py) is called with the saved training config
    and the planned scenario configs of that size, and the sha256 of the config it returns and the feature spec must
    equal the preflight and plan values. The returned mapping is keyed by N as a string. A missing
    model_preflight.json is not caught here.
    """
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


# matched: a list with one {policy: verified cell record} item per repetition (one scenario); every item must hold
# the records of the policy being summarized and of `reference`.
# equal_replicate[field] = describe() of the per-repetition values of FIELDS: every repetition has weight 1, whatever
# its packet count; a None is left out and counted in n_null. pooled_packet_and_call = sums over the repetitions
# (generated, delivered, failed, pending, delay_sum_s, route_calls, route_seconds, delivered_bytes) and ratios of
# those sums (delivered_mean_delay_s, failure_fraction, pending_fraction, nondelivery_fraction,
# route_seconds_per_call), None when the denominator is 0; goodput and simulation_seconds are not pooled.
# Paired differences (policies other than `reference` only): per repetition value(policy) - value(reference), None
# if either is None, then describe(). Units: see FIELDS.
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
    """Return (finished, marker) for <root>/execution_complete.json of a native plan; (False, None) if the file is absent.

    Every field must equal the expected record (schema, runs = number of planned cells, plan hash, the scope text,
    aggregation_supported and plots_supported False) except transport_finished, which may be True or False; any
    other difference, or a transport_finished that is not a bool, is a ValueError. The two False flags describe the
    transport step that wrote the marker; the summary's own scientific_consumer record says aggregation_supported True.
    """
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
    """Verify every planned cell from its saved files and write one summary JSON to `output`; return a small mapping.

    Order: scientific_plan_guard; ValueError if `reference` (default TBR_style_hop_oracle) is not in body["policies"];
    verify_models; scoped_declarations; _verify_cell for each cell in plan order (for a native plan KeyError, TypeError,
    AttributeError, OverflowError and OSError become ValueError, for other plans they are not converted; a ValueError
    from a cell check is raised also with allow_partial); the completion marker (native plan: native_completion_marker;
    other plans: execution_complete.json if present, which needs suite_finished True, the plan hash and runs equal to
    the number of cells, else ValueError); then the groups. complete = no missing cell and the marker found (native
    plan: with transport_finished true). If not complete and allow_partial is false, ValueError and nothing is written.
    The summary is the last thing written, by write() of experiment_io.py (mode x, exclusive creation). Paired
    differences are policy minus reference. Returns summary (path), sha256 (digest of the file), complete, groups (a
    count) and missing_or_failed_cells (a count; in the summary file that key is a list of cell ids).
    """
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
                # excluded_cells[<cell id>]: "missing job status" = no logs/<id>.status.json; "failed job" = exit_code is
                # not 0 or an exception is recorded; otherwise "missing completion artifact". experiment_plots accepts
                # exactly these three strings for native summaries.
                exclusions[cell["id"]] = (
                    "missing job status" if not status_path.exists() else
                    "failed job" if read(status_path).get("exit_code") != 0 or read(status_path).get("exception") is not None else
                    "missing completion artifact")
        else:
            verified[cell["scenario"]][cell["policy"]] = value
            evidence[cell["id"]] = {"result_sha256": value["result_sha256"], "traffic_sha256": value["traffic_sha256"]}
            if "enumeration" in value:
                evidence[cell["id"]]["enumeration"] = value["enumeration"]
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
    # A group is the set of scenarios that share (grid, variant, axis, x) through scenario["memberships"]; one scenario
    # can belong to several groups. A scenario is matched when every policy needed there is verified: all of
    # body["policies"] for an unscoped plan, the policies declared at that scenario for a scoped plan.
    # planned_repetitions = scenarios of the group; matched_repetitions = matched ones; included_seed_tuples and
    # excluded_seed_tuples = scenario["seeds"] of the matched and of the other scenarios. An unscoped plan passes the
    # matched scenarios to summarize_group; a scoped plan passes the per-scenario dicts of verified cells to
    # summarize_scoped_group. The three seeds are removed from a copy of each scenario config before comparing; the
    # rest (the controls) must be equal across the group, else ValueError (also with allow_partial).
    # controls["arrival_rate_packets_s"] = 1 / arrival_interval_s; the other controls are read from the first scenario.
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
        if ENUM_POLICY_NAME in body["policies"]:
            # T125: completeness of the enumeration searches over the cells that enter the estimates
            # (matched scenarios of an unscoped plan, present scenarios of a scoped plan).
            groups[-1]["enumeration_completeness"] = enumeration_completeness(
                [item[ENUM_POLICY_NAME]["enumeration"]
                 for item in (matched if declared is None else present) if ENUM_POLICY_NAME in item])
    # label, statistics, timing_warning and authentication_limit are fixed texts; the statistics text restates what
    # describe and summarize_group compute. experiment_plots refuses a summary whose label differs from its LABEL; for
    # native summaries it only requires statistics, timing_warning and authentication_limit to be non-empty strings.
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
    # Scoped plans only: policy_scope holds a copy of the suite's policy_scope (None if the suite is not a dict), a hash
    # of the [scenario id, declared policies] list, the declared cells per policy and the planned and verified cell
    # counts. absent_by_design_cells = scenarios x policies - planned cells: a policy that is not declared at a scenario
    # has no cell there and never appears in missing_or_failed_cells.
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
    # Only if TBR_enumeration is a planned policy: tbr_enumeration is a copy of body["tbr_enumeration"] (the plan options:
    # identity, the two budgets, incomplete_rule) and tbr_enumeration_note is a fixed reading text. The same policy adds
    # groups[*].enumeration_completeness and artifact_evidence[<cell id>]["enumeration"] (the verified diagnostics).
    if ENUM_POLICY_NAME in body["policies"]:
        document["tbr_enumeration"] = deepcopy(body["tbr_enumeration"])
        document["tbr_enumeration_note"] = ("TBR_enumeration is an iterative-deepening full enumeration with safety "
                                            "budgets, NOT the paper's brute force. A search that hits a budget is "
                                            "INCOMPLETE: the packet waits, no route is taken from partial work, and "
                                            "no other router is used. Read groups[*].enumeration_completeness "
                                            "before interpreting any TBR_enumeration estimate; its delay and loss "
                                            "include the effect of those waits. Timing is whole choose-call CPU wall "
                                            "time including incomplete calls, non-comparable to Fig.5.")
    # Native plan: the document built above is rewritten in place. suite_completion_marker_present is removed; schema
    # becomes NATIVE_SUMMARY_SCHEMA; timing_warning is replaced by the native text; producer_*, transport_*,
    # planned_cells, scientifically_verified_cells, excluded_cells and scientific_consumer are added.
    # scientific_consumer says plots_supported False (the scientific layer); experiment_plots keeps its own record,
    # PLOT_CONSUMER, for the plot layer.
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
