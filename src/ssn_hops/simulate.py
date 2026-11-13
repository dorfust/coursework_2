"""User-run single simulation CLI; sweep entry point is ssn_hops.experiments."""
# Commands: trace writes a traffic file; run runs one policy on one trace into a new output folder.
# SINGLE_POLICY_NAMES holds the names of POLICY_NAMES (imported from policies.py), the native
# bounded-exhaustive reference and TBR_enumeration. The files that run writes are listed in the
# docstring of run_single.
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
from time import perf_counter
from .config import canonical_json, from_dict, require_supported_model
from .contacts import build_geometric_plan
from .policies import POLICY_NAMES, ContactRouting, GLR, HopOracle, SourceDijkstra
from .provenance import file_sha256, provenance, read_json, write_json
from .sim_config import load_sim_config
from .simulator import simulate
from .tbr_enum import (DEFAULT_MAX_CALL_EXPANSIONS, DEFAULT_MAX_CELL_EXPANSIONS,
                       POLICY_NAME as ENUM_POLICY_NAME, TBR_enumeration)
from .tbr_policy import TBR_bounded_exhaustive_reference
from .tbr_reference import (
    DEFAULT_MAX_EXPANSIONS, DEFAULT_MAX_NODES, OBJECTIVE, SEARCH_IDENTITY,
    TBRIncompleteDetails, TBRSearchIncomplete,
)
from .traffic import make_trace, read_trace, trace_document

CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T003.md",
            "commit": "e1b644a701bae3e5f884d1623980d52bf99e6386", "step": "R2/A01/S01"}
# T022-S01 paper-fidelity repair: default input set is topology-only (paper-faithful);
# the propagation-delay channel is an optional extension. Contract blob is the file
# revision read when authoring; no commit hash is recorded (none was known).
FEATURE_CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T022-S01.md",
                    "blob": "f33277cd231492d48531c9f5da1769339e310a52",
                    "commit": None, "step": "T022/A01/S01"}
RESULT_SCHEMA = "ssn-simulation-result-v2"
NATIVE_POLICY_NAME = TBR_bounded_exhaustive_reference.name
# ONLY this command opts in. Do not extend legacy POLICY_NAMES or suite defaults.
# T125: the optional TBR_enumeration policy is registered here too (single-run command only;
# the experiment plans add it only through the plan option include_tbr_enumeration).
SINGLE_POLICY_NAMES = POLICY_NAMES + (NATIVE_POLICY_NAME, ENUM_POLICY_NAME)
NATIVE_RESULT_SCHEMA = "ssn-native-exhaustive-simulation-result-v1"
NATIVE_CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T011-S02-native-command.md",
                   "commit": "aae9530aa612972b77a854e893c0c02205288f52",
                   "blob": "b931d916a869d369ca9c2063270bead4dcaf20bf",
                   "step": "R3/A08/S02B1B"}


# Accepts 40 hexadecimal digits in either case and returns them in lower case.
def revision(value):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise argparse.ArgumentTypeError("record the actual 40-character checkout SHA")
    return value.lower()


def positive_cli_budget(value):
    # Decimal digits only: reject bool words, floats, signs and coercible strings.
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise argparse.ArgumentTypeError("TBR budget must be a positive decimal integer")
    return int(value)


def parser():
    root = argparse.ArgumentParser(description="Assumption-labeled dynamic routing; CPU timing only")
    commands = root.add_subparsers(dest="command", required=True)
    trace = commands.add_parser("trace", help="write a new immutable traffic JSON file")
    trace.add_argument("--config", required=True)
    trace.add_argument("--out", required=True)
    run = commands.add_parser("run", help="single policy/run; writes a NEW output directory")
    run.add_argument("--config", required=True)
    run.add_argument("--trace", required=True)
    run.add_argument("--policy", choices=SINGLE_POLICY_NAMES, required=True)
    run.add_argument("--checkpoint-run", help="complete trusted training run; required ONLY for GLR")
    run.add_argument("--tbr-max-nodes", type=positive_cli_budget, default=None,
                     help="native ONLY; independent safety bound (native default 12)")
    run.add_argument("--tbr-max-expansions", type=positive_cli_budget, default=None,
                     help="native ONLY; independent safety bound (native default 100000)")
    # The two --enum-max-* options are accepted only with the TBR_enumeration policy (run_single raises
    # ValueError otherwise), as the --tbr-* options are accepted only with the native policy. The help strings
    # quote the defaults as numbers; run_single takes them from DEFAULT_MAX_CALL_EXPANSIONS and
    # DEFAULT_MAX_CELL_EXPANSIONS, imported from tbr_enum.py.
    run.add_argument("--enum-max-call-expansions", type=positive_cli_budget, default=None,
                     help="TBR_enumeration ONLY; per-call safety bound (default 200000)")
    run.add_argument("--enum-max-cell-expansions", type=positive_cli_budget, default=None,
                     help="TBR_enumeration ONLY; per-cell safety bound (default 200000000)")
    # --p and --rate-bytes-s are parsed as floats and replace failure_probability and rate_bytes_s of the loaded
    # configuration in main(). The option name says bytes per second and its help text says bits/bytes; this file
    # only passes the number on. The summary text failure_protocol says "exact rational p"; this file does not
    # convert the float.
    run.add_argument("--p", type=float, help="override exact per-active-transfer-tick abort probability")
    run.add_argument("--rate-bytes-s", type=float, help="explicit bits/bytes sensitivity, e.g. 100000")
    run.add_argument("--out", required=True)
    run.add_argument("--revision", required=True, type=revision)
    return root


def run_single(cfg, records, policy_name, output, checkout_revision, checkpoint_run=None,
               input_paths=None, *, tbr_max_nodes=None, tbr_max_expansions=None,
               enum_max_call_expansions=None, enum_max_cell_expansions=None):
    """Run one policy on one trace into a NEW output folder and return the summary mapping.

    Order: cfg.validate(); the argument rules (the --tbr budgets only for the native policy, the enumeration
    budgets only for TBR_enumeration, checkpoint_run exactly for GLR; ValueError otherwise); for the native
    policy the node-count check, which raises TBRSearchIncomplete before the folder is created; then
    output.mkdir(parents=True, exist_ok=False); config.json, traffic.json, provenance.json; for GLR the model
    load and checks; simulate(); packets.json; events.jsonl; result.json (the summary, whose output_sha256
    covers config.json, traffic.json, provenance.json, packets.json and events.jsonl); complete.json last.
    An exception after the mkdir leaves a folder without complete.json; this function removes nothing.
    Exceptions of the policy construction or of simulate() are not caught here.
    """
    cfg.validate()
    if policy_name not in SINGLE_POLICY_NAMES:
        raise ValueError("unknown routing policy")
    native = policy_name == NATIVE_POLICY_NAME
    if not native and (tbr_max_nodes is not None or tbr_max_expansions is not None):
        raise ValueError("TBR budget options are supported only for the native single-run policy")
    if policy_name != ENUM_POLICY_NAME and (enum_max_call_expansions is not None
                                            or enum_max_cell_expansions is not None):
        raise ValueError("enumeration budget options are supported only for the TBR_enumeration policy")
    # checkpoint_run is required for GLR and refused for every other policy.
    if (policy_name == "GLR") != (checkpoint_run is not None):
        raise ValueError("--checkpoint-run is required only for GLR")
    native_reference = None
    if native:
        # The accepted constructor validates Integral types WITHOUT coercing bad API inputs.
        policy = TBR_bounded_exhaustive_reference(
            max_nodes=DEFAULT_MAX_NODES if tbr_max_nodes is None else tbr_max_nodes,
            max_expansions=DEFAULT_MAX_EXPANSIONS if tbr_max_expansions is None else tbr_max_expansions,
        )
        # Public command/API preflight, NOT a choose call or a synthetic search.
        # This covers empty traffic and every other run with no policy calls.
        if cfg.orbit.n > policy.max_nodes:
            raise TBRSearchIncomplete(TBRIncompleteDetails(
                reason="max_nodes", node_count=cfg.orbit.n, max_nodes=policy.max_nodes,
                max_expansions=policy.max_expansions, expansions=0,
            ))
        native_reference = {
            "policy_identity": NATIVE_POLICY_NAME,
            "search_identity": SEARCH_IDENTITY, "objective": OBJECTIVE,
            "max_nodes": policy.max_nodes, "max_expansions": policy.max_expansions,
            "budget_scope": "independent safety controls; NOT author settings",
            "scope": "opt-in single-run only; existing experiment loaders reject this native result schema; no suite/aggregation/plot integration",
            "node_preflight_scope": "run_single/CLI before output mkdir, including empty traffic; not a policy call; generic Simulator has no command preflight",
            "route_timing_scope": "whole choose call including adapter, core validation/search and counters; excludes context/masks; NOT pure core cost or author/Fig.5 equivalence",
            "authority": "independently specified bounded exhaustive reference; NOT recovered author traversal/code/performance",
            "contract": NATIVE_CONTRACT,
            "core_source_commit": "6df242596c554bb50c04a01eab9599cc54f4c52a",
            "adapter_source_commit": "245aa27a29b629f871ee9d29cf3e6d54c3b24e8a",
        }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    traffic = trace_document(records, cfg)
    write_json(output / "config.json", cfg.to_dict())
    write_json(output / "traffic.json", traffic)
    origin = provenance(checkout_revision)
    origin["simulation_contract"] = CONTRACT
    origin["feature_contract"] = FEATURE_CONTRACT
    origin["input_file_sha256"] = {str(path): file_sha256(path) for path in (input_paths or [])}
    if native:
        origin["native_reference"] = native_reference
    write_json(output / "provenance.json", origin)
    setup = {"model_load_seconds": None, "contact_plan_build_seconds": None,
             "torch_threads": cfg.torch_threads, "checkpoint": None}
    # The branches below do not include the native policy (built above) and have no final else.
    if policy_name == "GLR":
        # CPU is the ONLY supported simulator inference/timing device.
        # torch and the model and training modules are imported only in this branch. torch.set_num_threads and
        # torch.use_deterministic_algorithms are called here and are not set back in this function. The model
        # load and the checks below (light speed, orbit, phase seed) run after the output folder was created.
        import torch
        from .model import predict_hops
        from .training import load_trained_model
        torch.set_num_threads(cfg.torch_threads)
        torch.use_deterministic_algorithms(True)
        load_start = perf_counter()
        model, metadata = load_trained_model(checkpoint_run, "cpu")
        setup["model_load_seconds"] = perf_counter() - load_start
        training_config = from_dict(metadata["config"])
        # Mode-agnostic: topology-only (default) and the optional delay extension are both valid.
        require_supported_model(training_config.model)
        if training_config.model.uses_delay and cfg.light_speed_km_s != training_config.model.light_speed_km_s:
            # Light speed is only a constant of the optional delay channel D.
            raise ValueError("GLR simulation light speed differs from fixed model feature definition")
        if asdict(training_config.orbit) != asdict(cfg.orbit):
            raise ValueError("simulation orbit/N/planes/ID geometry differs from checkpoint")
        split_seeds = (training_config.data.train_seeds + training_config.data.val_seeds
                       + training_config.data.test_seeds)
        if cfg.phase_seed in split_seeds:
            raise ValueError("packet phase seed must not overlap training/validation/test phase seeds")
        setup["checkpoint"] = {"sha256": file_sha256(Path(checkpoint_run) / "best.pt"),
                               "training_config_sha256": metadata["config_sha256"],
                               "training_revision": metadata["revision"], "epoch": metadata["epoch"],
                               "feature_spec": training_config.model.feature_spec}
        # GLR passes ranges=None to the predictor in topology-only mode (see policies.GLR).
        policy = GLR(lambda adjacency, ranges: predict_hops(model, adjacency, ranges),
                     cfg.orbit.n, training_config.model)
    elif policy_name == "TBR_style_hop_oracle":
        policy = HopOracle()
    elif policy_name == "TSR_source_dijkstra":
        policy = SourceDijkstra()
    elif policy_name == ENUM_POLICY_NAME:
        # T125: optional full-enumeration TBR; budgets are safety controls, not paper settings.
        # This policy has no node-count check before the folder is created and no native_reference block; the
        # result schema stays RESULT_SCHEMA (only the native policy gets NATIVE_RESULT_SCHEMA).
        policy = TBR_enumeration(
            max_call_expansions=(DEFAULT_MAX_CALL_EXPANSIONS if enum_max_call_expansions is None
                                 else enum_max_call_expansions),
            max_cell_expansions=(DEFAULT_MAX_CELL_EXPANSIONS if enum_max_cell_expansions is None
                                 else enum_max_cell_expansions),
        )
    elif policy_name == "CGR_contact_plan":
        build_start = perf_counter()
        plan = build_geometric_plan(cfg)
        setup["contact_plan_build_seconds"] = perf_counter() - build_start
        policy = ContactRouting(plan)
    # Native policy was constructed/preflighted above. No fallback or catch:
    # typed incomplete propagates unchanged, BEFORE tables/result/complete writes.
    result = simulate(cfg, records, policy)
    write_json(output / "packets.json", {"schema": "ssn-packet-table-v1", "rows": result["packets"]})
    with (output / "events.jsonl").open("x", encoding="utf-8") as handle:
        for event in result["events"]:
            handle.write(canonical_json(event) + "\n")
    summary = result["summary"]
    # Version persisted command results, NOT packet lifecycle/accounting semantics.
    # assumptions, failure_protocol and runtime_origin are plain text labels stored in result.json; this file
    # does not open the documents named in them.
    summary.update({"schema": NATIVE_RESULT_SCHEMA if native else RESULT_SCHEMA, "config_sha256": cfg.sha256,
                    "traffic_sha256": traffic["sha256"],
                    "declared_checkout_revision": checkout_revision, "assumptions": "SIMULATION_PROTOCOL.md; R3_FEATURES.md",
                    "failure_protocol": "ssn-edge-tick-v1; exact rational p; unordered edge/tick; not persistent outages",
                    "runtime_origin": "only created when user executes; no precomputed paper results"})
    if native:
        summary["native_reference"] = native_reference
        summary["assumptions"] += "; TBR_NATIVE_SINGLE_RUN.md"
        # policy_details is the ACTUAL adapter snapshot supplied by Simulator.
        # Do not manufacture zero incomplete counters or completed-search totals.
    # model_load_seconds is set only in the GLR branch and contact_plan_build_seconds only in the CGR_contact_plan
    # branch; for the other policies setup leaves them None. Times are perf_counter() differences (seconds).
    # summary["timing"] is read here as an existing entry of the mapping returned by simulate().
    summary["timing"].update(setup)
    summary["timing"]["command_seconds_before_summary_write"] = perf_counter() - started
    summary["timing"]["command_scope"] = "after output mkdir; provenance, setup/lazy imports, simulation and table/events writes; excludes startup imports/input reads/final hashes/summary writes"
    summary["output_sha256"] = {name: file_sha256(output / name)
                                for name in ("config.json", "traffic.json", "provenance.json", "packets.json", "events.jsonl")}
    write_json(output / "result.json", summary)
    write_json(output / "complete.json", {"simulation_finished": True, "result_sha256": file_sha256(output / "result.json")})
    return summary


def main(argv=None):
    """Parse the arguments and run the trace or the run subcommand.

    trace: write the traffic file at --out (missing parent folders are created) and print traffic_file,
    sha256 and packets as JSON.
    run: --p and --rate-bytes-s replace failure_probability and rate_bytes_s of the loaded configuration; the
    changed configuration is validated and passed to read_trace and run_single, so config.json and
    config_sha256 in the result describe it. The summary returned by run_single is printed as JSON.
    main has no try block and no sys.exit call; it returns None.
    """
    args = parser().parse_args(argv)
    cfg = load_sim_config(args.config)
    if args.command == "trace":
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        document = trace_document(make_trace(cfg), cfg)
        write_json(output, document)
        print(json.dumps({"traffic_file": str(output), "sha256": document["sha256"],
                          "packets": len(document["records"])}, indent=2, allow_nan=False))
        return
    changes = {}
    if args.p is not None:
        changes["failure_probability"] = args.p
    if args.rate_bytes_s is not None:
        changes["rate_bytes_s"] = args.rate_bytes_s
    # The value returned by validate() is assigned to cfg, so validate() has to return the configuration.
    cfg = replace(cfg, **changes).validate()
    records = read_trace(read_json(args.trace), cfg)
    result = run_single(cfg, records, args.policy, args.out, args.revision,
                        args.checkpoint_run, [args.config, args.trace],
                        tbr_max_nodes=args.tbr_max_nodes, tbr_max_expansions=args.tbr_max_expansions,
                        enum_max_call_expansions=args.enum_max_call_expansions,
                        enum_max_cell_expansions=args.enum_max_cell_expansions)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
