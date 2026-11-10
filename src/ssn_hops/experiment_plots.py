"""Lazy reconstruction plots. Native support is a new, attributed consumer layer.

Summary consistency is checked here; saved science is NOT rerun or authenticated.
No matplotlib, simulator or search is imported by pure-data preparation.
"""
from collections import defaultdict
from copy import deepcopy
import math
from pathlib import Path
import re
from .config import content_hash
from .experiment_io import (NATIVE_PLAN_SCHEMA, NATIVE_POLICY_NAME, digest, native_options,
                            read, single_run_native_reference, write)
from .experiment_results import (FIELDS, SCIENTIFIC_CONTRACT, SUMMARY_SCHEMA,
                                 NATIVE_SUMMARY_SCHEMA, count, close, verify_native_counters)

LABEL = "RECONSTRUCTION / NOT AUTHORS' RESULTS"
PLOT_CONTRACT = {
    "path": "Repo_Orchestrator_2/tasks/T011-S02-native-plots.md",
    "commit": "160f93e55d22997ba8f9b34819e160e4d8b2d4de",
    "blob": "4a70a5e4325418bcd3de6c0b0ffe1c20f9e59745",
    "step": "R3/A12/S02B2C",
}
PLOT_CONSUMER = {
    "schema": "ssn-native-exhaustive-plot-consumer-v1", "contract": PLOT_CONTRACT,
    "plots_supported": True,
    "scope": "new native-summary plot consumer; original producer/transport/science declarations unchanged",
    "validation_limit": "summary consistency only; no rereading cell artifacts or rerunning science; hashes/counters are not anti-forgery or algorithm-execution proof",
    "timing_limit": "implementation CPU wall seconds only; author Fig.5 cost-axis unit and traversal unknown; no conversion or author equality",
}
METRICS = {"failure_probability": ("delivered_mean_delay_s", "failure_fraction", "pending_fraction"),
           "n": ("delivered_mean_delay_s", "route_seconds_per_call", "simulation_seconds")}
LABELS = {"delivered_mean_delay_s": "Delivered-only delay (seconds)",
          "failure_fraction": "Terminal failure fraction (failed/generated)",
          "pending_fraction": "Pending fraction (right-censored/generated)",
          "route_seconds_per_call": "CPU wall seconds per route call (including inference)",
          "simulation_seconds": "Whole simulator CPU wall seconds (NOT per-call)"}
NATIVE_LABELS = {**LABELS, "route_seconds_per_call": "Whole choose-call CPU wall seconds (NOT pure-core / author Fig.5)"}
ERROR_BARS = "one SE of the equal-replicate mean, NOT confidence intervals"
POLICIES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")
# T034 (R-1 / K001): the paper's Fig.5 (cost vs network scale) shows GLR, TBR and CGR only.
# Cost figures of axis "n" therefore omit TSR_source_dijkstra; the TSR cells stay in the
# summaries, and TSR stays on the delay figure of axis "n" and on every axis-failure_probability figure.
COST_METRICS = ("route_seconds_per_call", "simulation_seconds")
FIG5_POLICIES = ("GLR", "TBR_style_hop_oracle", "CGR_contact_plan", NATIVE_POLICY_NAME)
FIG5_EXCLUSION_REASON = "paper Fig.5 legend: GLR, TBR, CGR only"


def _same(actual, expected, label):
    if content_hash(actual) != content_hash(expected):
        raise ValueError("native summary " + label + " mismatch")


def _hash(value, length=64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise ValueError("native summary invalid hash/revision")


def _number(value, label, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (positive and value == 0)):
        raise ValueError("native summary invalid " + label)
    return value


def _stats(stats, matched):
    if set(stats) != {"n_total", "n_nonnull", "n_null", "mean", "sample_sd", "se_of_mean"}:
        raise ValueError("native summary statistics fields mismatch")
    total = count(stats["n_total"], "n_total")
    present = count(stats["n_nonnull"], "n_nonnull")
    absent = count(stats["n_null"], "n_null")
    if total != matched or present + absent != total:
        raise ValueError("native summary inconsistent matched/statistic counts")
    if present == 0:
        if any(stats[k] is not None for k in ("mean", "sample_sd", "se_of_mean")):
            raise ValueError("native summary null estimates must stay null")
        return
    # Paired differences may be negative; only finiteness is checked here.
    value = stats["mean"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("native summary invalid mean")
    if present == 1:
        if stats["sample_sd"] is not None or stats["se_of_mean"] is not None:
            raise ValueError("native summary one observation has null SD/SE")
    else:
        sd = _number(stats["sample_sd"], "sample SD")
        _number(stats["se_of_mean"], "SE")
        close(stats["se_of_mean"], sd / math.sqrt(present), "native summary SE")


def _seed_list(values):
    if not isinstance(values, list):
        raise ValueError("native summary seed list malformed")
    for triple in values:
        if (not isinstance(triple, list) or len(triple) != 3
                or any(type(v) is not int or not 0 <= v < 2**32 for v in triple)):
            raise ValueError("native summary seed tuple malformed")
    keys = [tuple(v) for v in values]
    if len(set(keys)) != len(keys):
        raise ValueError("native summary duplicate seed tuples")
    return set(keys)


def _validate_native(summary):
    """Consistency of the accepted summary shape, not full cell verification.

    Reuses frozen producer builders and scientific diagnostic guard read-only.
    A summary lacks the plan's scenario-to-seed mapping; only global evidence
    coverage and group count/seed consistency can be checked without the plan.
    """
    try:
        _same(summary["producer_plan_schema"], NATIVE_PLAN_SCHEMA, "producer schema")
        native = summary["producer_native_reference"]
        _same(native, native_options(True, native["max_nodes"], native["max_expansions"]), "producer reference")
        _same(summary["producer_single_run_reference"], single_run_native_reference(native), "single-run reference")
        scientific = {
            "contract": dict(SCIENTIFIC_CONTRACT), "aggregation_supported": True, "plots_supported": False,
            "scope": "strict saved-artifact scientific verification and complete planned-policy paired aggregation; plots unsupported",
            "counter_evidence": "verified saved native diagnostic types, identities, budgets, algebra and bounds; NOT proof of algorithm execution",
            "producer_scope_interpretation": "original single-run and transport declarations retained unchanged as historical layer claims; not retroactively relabeled",
        }
        _same(summary["scientific_consumer"], scientific, "scientific layer")
        _same(summary["field_units"], FIELDS, "units")
        _hash(summary["plan_sha256"])
        _hash(summary["declared_checkout_revision"], 40)
        sources = summary["source_sha256"]
        if not isinstance(sources, dict) or not sources or "experiment_results.py" not in sources or "experiment_plots.py" not in sources:
            raise ValueError("native summary missing source provenance")
        for key, value in sources.items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_]+\.py", key):
                raise ValueError("native summary malformed source filename")
            _hash(value)
        for key in ("statistics", "timing_warning", "authentication_limit"):
            if not isinstance(summary[key], str) or not summary[key]:
                raise ValueError("native summary missing limitations")
        if type(summary["complete"]) is not bool or type(summary["transport_finished"]) is not bool:
            raise ValueError("native summary completeness must be boolean")
        names = summary["policy_names"]
        expected_names = list(POLICIES[1:] if summary["mode"] == "baselines_only" else POLICIES) + [NATIVE_POLICY_NAME]
        if summary["mode"] not in ("baselines_only", "with_trained_GLR") or names != expected_names:
            raise ValueError("native summary unknown policy/order/mode")
        if summary["reference_policy"] not in names:
            raise ValueError("native summary reference policy not planned")
        features = summary["model_feature_specs"]
        if not isinstance(features, dict) or (summary["mode"] == "baselines_only" and features):
            raise ValueError("native summary model metadata mismatch")
        planned = count(summary["planned_cells"], "planned cells")
        verified = count(summary["scientifically_verified_cells"], "verified cells")
        if not planned or planned % len(names):
            raise ValueError("native summary planned cell count mismatch")
        missing = summary["missing_or_failed_cells"]
        evidence = summary["artifact_evidence"]
        exclusions = summary["excluded_cells"]
        if not isinstance(missing, list) or not isinstance(evidence, dict) or not isinstance(exclusions, dict):
            raise ValueError("native summary malformed evidence/exclusions")
        if (len(set(missing)) != len(missing) or set(missing) & set(evidence)
                or set(exclusions) != set(missing) or verified != len(evidence)
                or verified + len(missing) != planned):
            raise ValueError("native summary inconsistent evidence cell counts")
        if any(v not in ("missing job status", "failed job", "missing completion artifact") for v in exclusions.values()):
            raise ValueError("native summary unknown exclusion reason")
        scenarios = defaultdict(set)
        verified_scenarios = defaultdict(set)
        for cell_id in [*missing, *evidence]:
            if not isinstance(cell_id, str) or "--" not in cell_id:
                raise ValueError("native summary malformed cell id")
            scenario_id, policy = cell_id.split("--", 1)
            if not re.fullmatch(r"s-[0-9a-f]{16}", scenario_id) or policy not in names:
                raise ValueError("native summary unknown evidence policy/scenario")
            scenarios[scenario_id].add(policy)
            if cell_id not in evidence:
                continue
            verified_scenarios[scenario_id].add(policy)
            item = evidence[cell_id]
            if set(item) != {"result_sha256", "traffic_sha256", "output_sha256", "log_sha256", "native_counters"}:
                raise ValueError("native summary evidence fields mismatch")
            for key in ("result_sha256", "traffic_sha256"):
                _hash(item[key])
            for key, required in (("output_sha256", {"config.json", "traffic.json", "provenance.json", "packets.json", "events.jsonl"}),
                                  ("log_sha256", {".stdout.txt", ".stderr.txt"})):
                if set(item[key]) != required:
                    raise ValueError("native summary evidence hash map mismatch")
                for value in item[key].values():
                    _hash(value)
            if policy == NATIVE_POLICY_NAME:
                calls = item["native_counters"]["policy_calls"]
                verify_native_counters(item["native_counters"], native, {"route_calls": calls},
                                       {"transfer_and_route_counts": {"route_calls": calls}})
            elif item["native_counters"] is not None:
                raise ValueError("native summary baseline has native counters")
        if any(policies != set(names) for policies in scenarios.values()):
            raise ValueError("native summary incomplete planned-policy cell coverage")
        complete_scenarios = sum(policies == set(names) for policies in verified_scenarios.values())
        marker = summary["transport_completion_marker"]
        _same(summary["transport_completion_marker_present"], marker is not None, "marker presence")
        if marker is None:
            _same(summary["transport_finished"], False, "missing marker finished flag")
        else:
            if type(marker["transport_finished"]) is not bool:
                raise ValueError("native summary marker flag malformed")
            expected_marker = {
                "schema": "ssn-native-experiment-transport-complete-v1",
                "transport_finished": marker["transport_finished"], "runs": planned,
                "plan_sha256": summary["plan_sha256"], "aggregation_supported": False, "plots_supported": False,
                "scope": "all planned child artifacts transported; scientific verification/aggregation NOT performed",
            }
            _same(marker, expected_marker, "transport marker")
            _same(summary["transport_finished"], marker["transport_finished"], "transport finished flag")
        _same(summary["complete"], not missing and summary["transport_finished"], "completeness")
        groups = summary["groups"]
        if not isinstance(groups, list) or not groups:
            raise ValueError("native summary groups missing")
        for group in groups:
            for key in ("grid", "variant"):
                if not isinstance(group[key], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", group[key]):
                    raise ValueError("native summary unsafe plot name")
            axis = group["axis"]
            if axis not in METRICS:
                raise ValueError("unsupported plot axis")
            _hash(group["control_sha256"])
            repetitions = count(group["planned_repetitions"], "planned repetitions")
            matched = count(group["matched_repetitions"], "matched repetitions")
            if not repetitions or matched > repetitions or matched > complete_scenarios or repetitions > planned // len(names):
                raise ValueError("native summary inconsistent group matched counts")
            included = _seed_list(group["included_seed_tuples"])
            excluded = _seed_list(group["excluded_seed_tuples"])
            if len(included) != matched or len(excluded) != repetitions - matched or included & excluded:
                raise ValueError("native summary inconsistent group seed counts")
            if summary["complete"] and matched != repetitions:
                raise ValueError("native summary complete group has exclusions")
            c = group["controls"]
            for key in ("tick_s", "rate_bytes_s", "arrival_rate_packets_s", "traffic_end_s", "observation_end_s"):
                _number(c[key], "control " + key, positive=True)
            n = count(c["n"], "control N")
            planes = count(c["planes"], "control planes")
            p = _number(c["failure_probability"], "failure probability")
            if (n < 2 or not 1 <= planes <= n or n % planes or n > native["max_nodes"]
                    or p > 1 or c["observation_end_s"] < c["traffic_end_s"]):
                raise ValueError("native summary invalid controls/safety bound")
            x = _number(group["x"], "x")
            if x != (n if axis == "n" else p):
                raise ValueError("native summary x/control mismatch")
            if set(group["policies"]) != set(names) or set(group["paired_policy_minus_reference"]) != set(names) - {summary["reference_policy"]}:
                raise ValueError("native summary group policy mismatch")
            for policy in names:
                item = group["policies"][policy]
                if set(item) != {"equal_replicate", "pooled_packet_and_call"} or set(item["equal_replicate"]) != set(FIELDS):
                    raise ValueError("native summary policy statistics mismatch")
                for metric, stats in item["equal_replicate"].items():
                    _stats(stats, matched)
                    if stats["mean"] is not None:
                        _number(stats["mean"], "metric mean")
                        if metric.endswith("fraction") and stats["mean"] > 1:
                            raise ValueError("native summary fraction outside [0,1]")
                totals = item["pooled_packet_and_call"]
                for key in ("generated", "delivered", "failed", "pending", "route_calls", "delivered_bytes"):
                    count(totals[key], key)
                if totals["generated"] != totals["delivered"] + totals["failed"] + totals["pending"]:
                    raise ValueError("native summary pooled conservation mismatch")
                for key in ("delay_sum_s", "route_seconds"):
                    _number(totals[key], key)
                for metric, denominator in (("delivered_mean_delay_s", "delivered"), ("route_seconds_per_call", "route_calls"),
                                            ("failure_fraction", "generated"), ("pending_fraction", "generated"), ("nondelivery_fraction", "generated")):
                    if totals[denominator] == 0 and item["equal_replicate"][metric]["n_nonnull"] != 0:
                        raise ValueError("native summary empty denominator must be a null gap")
                if not matched and any(totals[k] != 0 for k in ("generated", "delivered", "failed", "pending", "route_calls", "delivered_bytes", "delay_sum_s", "route_seconds")):
                    raise ValueError("native summary zero matched group has pooled work")
            for paired in group["paired_policy_minus_reference"].values():
                if set(paired) != set(FIELDS):
                    raise ValueError("native summary paired fields mismatch")
                for stats in paired.values():
                    _stats(stats, matched)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("malformed native summary metadata") from exc


def _policy_label(policy, native):
    if policy == "TBR_style_hop_oracle":
        return policy + " (BFS practical alternative; NON-COMPARABLE to Fig.5)"
    if native and policy == NATIVE_POLICY_NAME:
        return (policy + " (bounded exhaustive; whole choose CPU wall time; NOT pure-core / author Fig.5)"
                + f"\nSafety limits: max_nodes={native['max_nodes']}, max_expansions={native['max_expansions']} (NOT author settings)")
    return policy


def prepare_plots(summary, allow_partial=False):
    """Pure-data preparation; preserve equal-replicate values, SE and null gaps."""
    if not isinstance(summary, dict) or summary.get("schema") not in (SUMMARY_SCHEMA, NATIVE_SUMMARY_SCHEMA) or summary.get("label") != LABEL:
        raise ValueError("only explicitly labeled experiment summaries are accepted")
    is_native = summary["schema"] == NATIVE_SUMMARY_SCHEMA
    if is_native:
        _validate_native(summary)
    if summary["complete"] is not True and not allow_partial:
        raise ValueError("partial suite plots require --allow-partial and explicit labeling")
    native = summary["producer_native_reference"] if is_native else None
    buckets = defaultdict(list)
    for group in summary["groups"]:
        if group["axis"] not in METRICS:
            raise ValueError("unsupported plot axis")
        buckets[(group["grid"], group["variant"], group["axis"])].append(group)
    specifications = []
    for (grid, variant, axis), groups in sorted(buckets.items()):
        groups = sorted(groups, key=lambda g: g["x"])
        if len({g["x"] for g in groups}) != len(groups):
            raise ValueError("duplicate x in plot series")
        controls = groups[0]["controls"]
        fixed_keys = ["tick_s", "rate_bytes_s", "arrival_rate_packets_s", "traffic_end_s", "observation_end_s"]
        if is_native:
            fixed_keys += ["failure_probability"] if axis == "n" else ["n", "planes"]
        fixed = tuple(controls[k] for k in fixed_keys)
        for group in groups:
            if tuple(group["controls"][k] for k in fixed_keys) != fixed:
                raise ValueError("plot would silently mix rate/tick/load/window controls")
        for metric in METRICS[axis]:
            # Fig.5-analogue cost figure (axis n, cost metric): GLR/TBR/CGR (+ native TBR) only.
            cost_figure = axis == "n" and metric in COST_METRICS
            shown = [p for p in summary["policy_names"] if not cost_figure or p in FIG5_POLICIES]
            if not shown:
                raise ValueError("no Fig.5 policy available for a cost plot")
            curves = []
            for policy in shown:
                stats = [g["policies"][policy]["equal_replicate"][metric] for g in groups]
                curve = {"policy": policy, "label": _policy_label(policy, native), "x": [g["x"] for g in groups],
                         "y": [s["mean"] for s in stats], "se": [s["se_of_mean"] for s in stats],
                         "nonnull_repetitions": [s["n_nonnull"] for s in stats],
                         "matched_repetitions": [g["matched_repetitions"] for g in groups]}
                if is_native:
                    curve.update({"null_repetitions": [s["n_null"] for s in stats],
                                  "planned_repetitions": [g["planned_repetitions"] for g in groups],
                                  "statistics_source": "policies[policy].equal_replicate; NOT pooled or surviving-policy subsets",
                                  "method_limitations": _policy_label(policy, native)})
                curves.append(curve)
            spec = {"filename": f"{grid}--{variant}--{metric}.png", "grid": grid, "variant": variant,
                    "axis": axis, "metric": metric, "controls": deepcopy(controls), "curves": curves,
                    "partial": summary["complete"] is not True}
            if cost_figure:
                spec.update({"excluded_policies": [p for p in summary["policy_names"] if p not in shown],
                             "exclusion_reason": FIG5_EXCLUSION_REASON})
            if is_native:
                spec.update({"input_summary_schema": summary["schema"], "plot_consumer": deepcopy(PLOT_CONSUMER),
                             "ylabel": NATIVE_LABELS[metric], "error_bars": ERROR_BARS,
                             "display_label": LABEL + (" / PARTIAL" if spec["partial"] else ""),
                             "controls_by_x": [deepcopy(g["controls"]) for g in groups],
                             "count_provenance": [{key: deepcopy(g[key]) for key in
                                                   ("x", "control_sha256", "planned_repetitions", "matched_repetitions", "included_seed_tuples", "excluded_seed_tuples")} for g in groups],
                             "native_safety_limits": {key: native[key] for key in ("max_nodes", "max_expansions", "budget_scope")}})
            specifications.append(spec)
    if is_native and len({s["filename"] for s in specifications}) != len(specifications):
        raise ValueError("native summary colliding plot filenames")
    return specifications


def prepare_plot_data(summary, summary_sha256=None, allow_partial=False):
    """New data-only export helper. Caller supplies file hash, not a measurement."""
    specs = prepare_plots(summary, allow_partial)
    document = {"summary_sha256": summary_sha256, "plots": specs, "error_bars": ERROR_BARS}
    if summary["schema"] == NATIVE_SUMMARY_SCHEMA:
        if summary_sha256 is not None:
            _hash(summary_sha256)
        document.update({"input_summary_schema": summary["schema"], "plot_consumer": deepcopy(PLOT_CONSUMER),
                         "label": LABEL + (" / PARTIAL" if not summary["complete"] else ""),
                         "partial": not summary["complete"],
                         "input_layers": {key: deepcopy(summary[key]) for key in
                                          ("producer_plan_schema", "producer_native_reference", "producer_single_run_reference", "scientific_consumer", "transport_completion_marker")},
                         "summary_provenance": {key: deepcopy(summary[key]) for key in
                                                ("plan_sha256", "declared_checkout_revision", "source_sha256", "reference_policy", "scientifically_verified_cells", "planned_cells", "missing_or_failed_cells", "excluded_cells", "artifact_evidence", "statistics", "timing_warning", "authentication_limit")}})
    return document


def plot_summary(summary_path, output, allow_partial=False):
    input_hash = digest(summary_path)
    summary = read(summary_path)
    data = prepare_plot_data(summary, input_hash, allow_partial)
    if digest(summary_path) != input_hash:
        raise ValueError("summary changed during plot preparation")
    specs = data["plots"]
    # Import ONLY after all native validation; missing package creates no output.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write(root / "plot_data.json", data)
    for spec in specs:
        figure, axes = plt.subplots(figsize=(10, 6), constrained_layout=True)
        try:
            for curve in spec["curves"]:
                values = [v if v is not None else math.nan for v in curve["y"]]
                line, = axes.plot(curve["x"], values, marker="o", label=curve["label"])
                for x, y, se in zip(curve["x"], curve["y"], curve["se"]):
                    if y is not None and se is not None:
                        axes.errorbar([x], [y], yerr=[se], color=line.get_color(), capsize=3)
            c = spec["controls"]
            axes.set_title(LABEL + (" / PARTIAL" if spec["partial"] else "")
                           + f"\n{spec['grid']} / {spec['variant']} / {summary['mode']}"
                           + f"\ndt={c['tick_s']} s; rate={c['rate_bytes_s']} B/s; load={c['arrival_rate_packets_s']:g} packets/s")
            axes.set_xlabel("Per-active-transfer-tick abort probability p" if spec["axis"] == "failure_probability" else "Constellation size N")
            axes.set_ylabel(spec.get("ylabel", LABELS[spec["metric"]]))
            axes.grid(True, alpha=0.25)
            axes.legend(fontsize="small")
            figure.text(0.01, 0.005, "Equal-replicate means; bars = 1 SE, not CI. Null estimates are gaps. Matched/nonnull counts in plot_data.json.", fontsize=8)
            figure.savefig(root / spec["filename"], dpi=150)
        finally:
            plt.close(figure)
    if digest(summary_path) != input_hash:
        raise ValueError("summary changed during rendering; no completion claim")
    complete = {"plots_finished": True, "summary_sha256": input_hash,
                "output_sha256": {s["filename"]: digest(root / s["filename"]) for s in specs},
                "plot_data_sha256": digest(root / "plot_data.json")}
    if summary["schema"] == NATIVE_SUMMARY_SCHEMA:
        complete.update({"input_summary_schema": summary["schema"], "plot_consumer": deepcopy(PLOT_CONSUMER),
                         "partial": not summary["complete"]})
    write(root / "complete.json", complete)
    return {"plots": len(specs), "out": str(root), "partial": summary["complete"] is not True}
