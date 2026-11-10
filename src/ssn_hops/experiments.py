"""Offline plans and USER-invoked sequential execution. Runtime status: not_run."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
from .config import content_hash, from_dict, require_supported_model
from .experiment_io import (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA, NATIVE_POLICY_NAME,
                            digest, execution_guard, inside, job, load_plan,
                            native_options, native_transport_check, read,
                            revision, source_hashes, write)
from .sim_config import from_sim_dict

POLICIES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")
SUITE_SCHEMA = "ssn-experiment-suite-v1"
# T057-S01 (R8, P-1): the nine required suite keys are ONE constant; the only optional key is
# policy_scope (see validate_policy_scope). A suite WITHOUT it is validated and planned exactly as before.
SUITE_REQUIRED_KEYS = frozenset({"schema", "name", "core_template", "simulation_template",
                                 "training_overrides", "simulation_overrides", "seed_tuples",
                                 "grids", "sensitivities"})
SUITE_OPTIONAL_KEYS = frozenset({"policy_scope"})
POLICY_SCOPE_FILTERS = ("n", "failure_probability", "seed_tuple_indices")
CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T003-sweeps.md",
            "commit": "9e52079512f0fb039955aeae7e9e0ce1102571b6", "step": "R2/A01/S02"}
# T022-S01 paper-fidelity repair: default input set is topology-only (paper-faithful);
# the propagation-delay channel is an optional extension. MUST stay identical to
# simulate.FEATURE_CONTRACT. Contract blob = file revision read when authoring; no commit hash invented.
FEATURE_CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T022-S01.md",
                    "blob": "f33277cd231492d48531c9f5da1769339e310a52",
                    "commit": None, "step": "T022/A01/S01"}


def merge(base, changes):
    result = deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", value):
        raise ValueError("names must be short lowercase alphanumeric identifiers")
    return value


def suite_keys_valid(suite):
    """Required keys all present; no key outside required + optional (a suite without policy_scope: exact set)."""
    keys = set(suite)
    return SUITE_REQUIRED_KEYS <= keys <= (SUITE_REQUIRED_KEYS | SUITE_OPTIONAL_KEYS)


def validate_policy_scope(suite):
    """T057-S01 (R8, P-1): strict validation of the OPTIONAL suite key ``policy_scope``.

    Schema: a nonempty mapping policy name -> filter mapping. Policy names must be in POLICIES
    (the native policy is NOT scopable). A filter mapping has only the keys n, failure_probability,
    seed_tuple_indices (each optional; an omitted key means 'all'; an empty mapping means 'everywhere').
    Each present value is a list (an EMPTY list is legal and means 'this policy nowhere'), without
    duplicates, whose members exist in the suite: n in some grid size (type int), failure_probability
    in some grid probability (finite int/float, compared by exact == with the grid value as parsed;
    no tolerance; 0 equals 0.0), seed_tuple_indices in range(len(seed_tuples)) (type int, not bool).
    A policy that is not named runs everywhere. Runs after the baseline suite validation.
    """
    scope = suite["policy_scope"]
    if not isinstance(scope, dict) or not scope:
        raise ValueError("policy_scope must be a nonempty mapping from policy name to filters")
    try:
        sizes = {size["n"] for grid in suite["grids"] for size in grid["sizes"]}
        probabilities = {p for grid in suite["grids"] for p in grid["probabilities"]}
    except (KeyError, TypeError):
        raise ValueError("policy_scope requires well-formed grids") from None
    indices = range(len(suite["seed_tuples"]))
    for policy, rule in scope.items():
        if policy not in POLICIES:
            raise ValueError(f"policy_scope names an unknown policy: {policy!r}")
        if not isinstance(rule, dict):
            raise ValueError(f"policy_scope filters of {policy} must be a mapping")
        if set(rule) - set(POLICY_SCOPE_FILTERS):
            raise ValueError("policy_scope filter keys are n, failure_probability, seed_tuple_indices only")
        for key, values in rule.items():
            if not isinstance(values, list):
                raise ValueError(f"policy_scope {key} must be a list (empty list = policy nowhere)")
            for value in values:
                if key == "failure_probability":
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError("policy_scope failure_probability values must be finite numbers")
                    if value not in probabilities:
                        raise ValueError("policy_scope failure_probability value not in any suite grid")
                else:
                    if type(value) is not int:
                        raise ValueError(f"policy_scope {key} values must be integers")
                    if key == "n" and value not in sizes:
                        raise ValueError("policy_scope n value not in any suite grid")
                    if key == "seed_tuple_indices" and value not in indices:
                        raise ValueError("policy_scope seed tuple index outside seed_tuples")
            if len(set(values)) != len(values):
                raise ValueError(f"policy_scope duplicate values in {key}")


def scope_policies(scope, n, probability, index, active):
    """Policies (canonical order, restricted to ``active``) planned for one scenario point.

    A policy not named in ``scope`` runs everywhere; a named policy runs iff every PRESENT filter
    contains the scenario's N, failure probability (exact ==) and seed-tuple index.
    """
    chosen = []
    for policy in active:
        rule = scope.get(policy)
        if rule is not None and not (
                ("n" not in rule or n in rule["n"])
                and ("failure_probability" not in rule or probability in rule["failure_probability"])
                and ("seed_tuple_indices" not in rule or index in rule["seed_tuple_indices"])):
            continue
        chosen.append(policy)
    return chosen


def validate_suite(suite, core, sim):
    """Validate saved resolved inputs too, without importing any ML modules."""
    if not suite_keys_valid(suite) or suite["schema"] != SUITE_SCHEMA:
        raise ValueError("invalid suite fields/schema")
    name(suite["name"])
    triples = suite["seed_tuples"]
    if not isinstance(triples, list) or len(triples) < 5:
        raise ValueError("suite must declare at least five seed tuples")
    flattened = []
    for triple in triples:
        if not isinstance(triple, list) or len(triple) != 3:
            raise ValueError("each tuple is [phase, traffic, failure]")
        for seed in triple:
            if type(seed) is not int or not 0 <= seed < 2**32:
                raise ValueError("invalid experiment seed")
        flattened.extend(triple)
    if len(set(flattened)) != len(flattened):
        raise ValueError("experiment seed tuples must be disjoint, including streams")
    training_seeds = (core.data.train_seeds + core.data.val_seeds + core.data.test_seeds
                      + [core.train.seed])
    if set(flattened) & set(training_seeds):
        raise ValueError("experiment and core seeds overlap")
    if not suite["grids"] or not suite["sensitivities"]:
        raise ValueError("grids and sensitivities must be nonempty")
    if len({name(g["name"]) for g in suite["grids"]}) != len(suite["grids"]):
        raise ValueError("duplicate grid names")
    if len({name(v["name"]) for v in suite["sensitivities"]}) != len(suite["sensitivities"]):
        raise ValueError("duplicate sensitivity names")
    allowed = {"tick_s", "rate_bytes_s", "arrival_interval_s"}
    for variant in suite["sensitivities"]:
        if set(variant) != {"name", "overrides"} or set(variant["overrides"]) - allowed:
            raise ValueError("sensitivity overrides are tick/rate/arrival interval only")
    core.validate()
    sim.validate()
    if "policy_scope" in suite:
        validate_policy_scope(suite)


def resolve_suite(suite_path):
    suite_path = Path(suite_path).resolve()
    suite = read(suite_path)
    if not suite_keys_valid(suite) or suite["schema"] != SUITE_SCHEMA:
        raise ValueError("invalid suite fields/schema")
    core = from_dict(merge(read(suite_path.parent / suite["core_template"]), suite["training_overrides"]))
    sim = from_sim_dict(merge(read(suite_path.parent / suite["simulation_template"]), suite["simulation_overrides"]))
    validate_suite(suite, core, sim)
    return suite, core, sim


def resolve_plan_inputs(suite, core, sim, root, models, baselines_only, native=None):
    """Pure resolution shared with strict native loading; legacy ordering retained.

    T057-S01: ONLY when the suite carries policy_scope, every scenario additionally gets
    ``policies`` (canonical POLICIES order, restricted to the policies active in this mode, i.e.
    GLR is dropped under baselines_only). Scenario ids, keys, configs and memberships do not depend
    on the scope. Trainings/models stay per N of the suite grids (scope never removes a training).
    """
    scenarios = {}
    training = {}
    sizes = {}
    scope = suite.get("policy_scope")
    active = POLICIES[1:] if baselines_only else POLICIES
    for grid in suite["grids"]:
        if set(grid) != {"name", "axis", "sizes", "probabilities"} or grid["axis"] not in ("n", "failure_probability"):
            raise ValueError("invalid grid fields/axis")
        if not grid["sizes"] or not grid["probabilities"]:
            raise ValueError("empty grid")
        if len(set(grid["probabilities"])) != len(grid["probabilities"]):
            raise ValueError("duplicate grid probabilities")
        local_sizes = set()
        for size in grid["sizes"]:
            if set(size) != {"n", "planes"}:
                raise ValueError("size requires N and planes")
            n = size["n"]
            if n in local_sizes or (n in sizes and sizes[n] != size["planes"]):
                raise ValueError("duplicate size or inconsistent N/planes pairing")
            local_sizes.add(n)
            sizes[n] = size["planes"]
            train_cfg = from_dict(merge(core.to_dict(), {"orbit": size}))
            training[str(n)] = {"config": train_cfg.to_dict(), "config_sha256": train_cfg.sha256,
                                "feature_spec": train_cfg.model.feature_spec,
                                "config_path": f"configs/training-n{n}.json",
                                "supplied": str(n) in models,
                                "run": str(Path(models[str(n)]).resolve()) if str(n) in models
                                       else str(root / f"training/n{n}/run"),
                                "data": str(root / f"training/n{n}/data")}
            for p in grid["probabilities"]:
                for variant in suite["sensitivities"]:
                    for index, triple in enumerate(suite["seed_tuples"]):
                        cfg = from_sim_dict(merge(sim.to_dict(), {"orbit": size,
                            "failure_probability": p, "phase_seed": triple[0],
                            "traffic_seed": triple[1], "failure_seed": triple[2],
                            **variant["overrides"]}))
                        # Planning preflight for EVERY scenario, independent of traffic.
                        # ValueError is validation, NOT a completed/incomplete core search.
                        if native is not None and cfg.orbit.n > native["max_nodes"]:
                            raise ValueError(f"native node preflight: resolved N={cfg.orbit.n} exceeds "
                                             f"max_nodes={native['max_nodes']}; no search performed")
                        if not baselines_only:
                            check_model(train_cfg.to_dict(), [cfg.to_dict()])
                        key = content_hash({"config": cfg.to_dict(), "variant": variant["name"]})
                        scenario_id = "s-" + key[:16]
                        scoped = None
                        if scope is not None:
                            scoped = scope_policies(scope, n, p, index, active)
                            if not scoped:
                                raise ValueError("policy_scope leaves a scenario without any active policy")
                        membership = {"grid": grid["name"], "axis": grid["axis"],
                                      "x": n if grid["axis"] == "n" else p}
                        if scenario_id not in scenarios:
                            scenarios[scenario_id] = {"id": scenario_id, "key": key,
                                "config": cfg.to_dict(), "config_sha256": cfg.sha256,
                                "config_path": f"configs/{scenario_id}.json",
                                "trace_path": f"traces/t-{cfg.trace_key}.json",
                                "variant": variant["name"], "seeds": triple, "memberships": []}
                            if scoped is not None:
                                scenarios[scenario_id]["policies"] = scoped
                        scenario = scenarios[scenario_id]
                        if scenario["key"] != key:
                            raise ValueError("short scenario ID hash collision")
                        if scoped is not None and scenario["policies"] != scoped:
                            raise ValueError("inconsistent policy_scope for a shared scenario")
                        if membership not in scenario["memberships"]:
                            scenario["memberships"].append(membership)
    if set(models) - set(training):
        raise ValueError("model mapping contains a size outside the suite")
    memberships = set()
    for scenario in scenarios.values():
        for member in scenario["memberships"]:
            key = (member["grid"], scenario["variant"], member["x"], tuple(scenario["seeds"]))
            if key in memberships:
                raise ValueError("ambiguous grid: multiple controls per seed/x")
            memberships.add(key)
    return training, list(scenarios.values())


def plan_commands(root, training, scenarios, policies, checkout_revision, native=None):
    """Construct exact argv without execution; mutates only resolved training steps.

    A scenario carrying ``policies`` (T057-S01, policy_scope plans only) gets cells for exactly that
    list; every other scenario gets one cell per entry of ``policies`` as before. Child command
    text and out paths of a cell do not depend on the scope.
    """
    commands = []
    for n, item in training.items():
        config_path = str(root / item["config_path"])
        item["steps"] = [
            {"id": f"data-n{n}", "command": ["python", "-m", "ssn_hops", "generate", "--config", config_path,
                "--out", item["data"], "--revision", checkout_revision]},
            {"id": f"train-n{n}", "command": ["python", "-m", "ssn_hops", "train", "--config", config_path,
                "--data", item["data"], "--out", item["run"], "--revision", checkout_revision]},
            {"id": f"evaluate-n{n}", "command": ["python", "-m", "ssn_hops", "evaluate", "--run", item["run"],
                "--data", item["data"], "--split", "test", "--device", "cpu", "--out",
                str(root / f"training/n{n}/test.json"), "--revision", checkout_revision]}]
        commands.extend(item["steps"])
    cells = []
    for scenario in scenarios:
        commands.append({"id": "trace-" + scenario["id"], "command": ["python", "-m", "ssn_hops.simulate",
            "trace", "--config", str(root / scenario["config_path"]), "--out", str(root / scenario["trace_path"])]})
        for policy in (scenario["policies"] if "policies" in scenario else policies):
            cell_id = scenario["id"] + "--" + policy
            relative_out = f"runs/{cell_id}"
            command = ["python", "-m", "ssn_hops.simulate", "run", "--config", str(root / scenario["config_path"]),
                "--trace", str(root / scenario["trace_path"]), "--policy", policy,
                "--out", str(root / relative_out), "--revision", checkout_revision]
            if policy == "GLR":
                command.extend(["--checkpoint-run", training[str(scenario["config"]["orbit"]["n"])]["run"]])
            if policy == NATIVE_POLICY_NAME:
                command.extend(["--tbr-max-nodes", str(native["max_nodes"]),
                                "--tbr-max-expansions", str(native["max_expansions"])])
            cells.append({"id": cell_id, "scenario": scenario["id"], "policy": policy,
                          "config_path": scenario["config_path"], "out": relative_out, "command": command})
    return commands, cells


def make_plan(suite_path, output, checkout_revision, models=None, baselines_only=False, *,
              include_native_tbr=False, tbr_max_nodes=None, tbr_max_expansions=None):
    """Write configurations/commands ONLY; no imports of torch or simulator.

    The five legacy positional arguments retain their meaning. New options are
    keyword-only, native-only safety controls, NOT recovered author settings.
    A suite with the optional key policy_scope (T057-S01) is rejected together with
    include_native_tbr (the native plan schema is frozen); otherwise body['policies'] is the
    union of the scenario policy lists in canonical order.
    """
    native = native_options(include_native_tbr, tbr_max_nodes, tbr_max_expansions)
    checkout_revision = revision(checkout_revision)
    suite, core, sim = resolve_suite(suite_path)
    if native is not None and "policy_scope" in suite:
        raise ValueError("policy_scope is not supported by native plans (native schema is frozen)")
    if not baselines_only:
        # Mode-agnostic: topology-only (default) and the optional delay extension both plan.
        require_supported_model(core.model)
    root = Path(output).resolve()
    if root.exists():
        raise FileExistsError("plan output must be a new directory")
    policies = list(POLICIES[1:] if baselines_only else POLICIES)
    if native is not None:
        policies.append(NATIVE_POLICY_NAME)
    models = models or {}
    if not isinstance(models, dict) or any(not isinstance(k, str) or not k.isdigit()
                                          or not isinstance(v, str) for k, v in models.items()):
        raise ValueError("models JSON must map decimal N strings to trusted complete run paths")
    training, scenarios = resolve_plan_inputs(suite, core, sim, root, models, baselines_only, native)
    if "policy_scope" in suite:
        declared = {policy for scenario in scenarios for policy in scenario["policies"]}
        policies = [policy for policy in POLICIES if policy in declared]
    commands, cells = plan_commands(root, training, scenarios, policies, checkout_revision, native)
    body = {"suite": suite, "revision": checkout_revision, "root": str(root), "contract": CONTRACT,
            "feature_contract": FEATURE_CONTRACT,
            "mode": "baselines_only" if baselines_only else "with_trained_GLR",
            "source_sha256": source_hashes(), "policies": policies, "models": training,
            "scenarios": scenarios, "cells": cells, "offline_steps": commands,
            "file_sha256": {}, "execution": "sequential user invocation only; no resume/overwrite"}
    if native is not None:
        body["native_reference"] = native
        body["resolved_templates"] = {"core": core.to_dict(), "simulation": sim.to_dict()}
    # ALL native scenario/budget validation above precedes the first mkdir/write.
    root.mkdir(parents=True, exist_ok=False)
    for item in [*training.values(), *scenarios]:
        write(root / item["config_path"], item["config"])
        body["file_sha256"][item["config_path"]] = digest(root / item["config_path"])
    document = {"schema": NATIVE_PLAN_SCHEMA if native is not None else PLAN_SCHEMA,
                "body": body, "sha256": content_hash(body)}
    write(root / "plan.json", document)
    return {"plan": str(root / "plan.json"), "sha256": document["sha256"], "mode": body["mode"],
            "models_required": sorted(training), "scenarios": len(scenarios), "runs": len(cells)}


def check_model(training_cfg, scenario_configs, expected_model_config=None):
    """Metadata compatibility, independent of tensor execution; useful for tests.

    Mode-agnostic validity (topology-only default or optional delay extension), with
    STRICT equality against expected_model_config so a checkpoint of one feature mode
    never satisfies a plan of another.
    """
    cfg = from_dict(training_cfg)
    require_supported_model(cfg.model)
    if expected_model_config is not None and cfg.model != expected_model_config:
        raise ValueError("checkpoint model/input configuration differs from planned model")
    split_seeds = cfg.data.train_seeds + cfg.data.val_seeds + cfg.data.test_seeds
    for simulation in scenario_configs:
        simulation = from_sim_dict(simulation)
        if asdict(cfg.orbit) != asdict(simulation.orbit):
            raise ValueError("checkpoint orbit/N/planes differs from simulation")
        if cfg.model.uses_delay and simulation.light_speed_km_s != cfg.model.light_speed_km_s:
            # Light speed is only a constant of the optional delay channel D.
            raise ValueError("simulation light speed differs from model feature definition")
        if simulation.phase_seed in split_seeds:
            raise ValueError("checkpoint split phase seed overlaps experiment")
    return cfg


def preflight_models(plan):
    body = plan["body"]
    if "GLR" not in body["policies"]:
        return {}
    # Validate ALL required trained models before any costly simulation.
    from .training import load_trained_model
    records = {}
    for n, item in body["models"].items():
        expected = from_dict(item["config"]).model
        model, metadata = load_trained_model(item["run"], "cpu", expected)
        configs = [s["config"] for s in body["scenarios"] if str(s["config"]["orbit"]["n"]) == n]
        cfg = check_model(metadata["config"], configs, expected)
        if item["feature_spec"] != cfg.model.feature_spec:
            raise ValueError("planned feature spec differs from checkpoint")
        records[n] = {"run": item["run"], "checkpoint_sha256": digest(Path(item["run"]) / "best.pt"),
                      "training_config_sha256": metadata["config_sha256"], "training_revision": metadata["revision"],
                      "epoch": metadata["epoch"], "feature_spec": cfg.model.feature_spec}
        del model
    return records


def train_suite(plan, checkout_revision):
    execution_guard(plan, checkout_revision)
    root = Path(plan["body"]["root"])
    unsupplied = [m for m in plan["body"]["models"].values() if not m["supplied"]]
    for item in unsupplied:
        if Path(item["run"]).exists() or Path(item["data"]).exists():
            raise FileExistsError("training/data path already exists; partial runs cannot be resumed")
    write(root / "training_started.json", {"plan_sha256": plan["sha256"], "revision": checkout_revision})
    for item in unsupplied:
        for step in item["steps"]:
            job(root, step["id"], step["command"], plan)
    write(root / "training_complete.json", {"steps_finished": True,
          "new_models": len(unsupplied), "supplied_models_skipped": len(plan["body"]["models"]) - len(unsupplied)})
    return {"training_finished": True, "new_models": len(unsupplied)}


def execute_suite(plan, checkout_revision):
    execution_guard(plan, checkout_revision)
    root = Path(plan["body"]["root"])
    # No stale run or trace reuse, even after a failed invocation.
    for relative in ("execution_started.json", "runs", "traces", "model_preflight.json"):
        if inside(root, relative).exists():
            raise FileExistsError("execution artifacts already exist; create a fresh plan")
    models = preflight_models(plan)
    write(root / "model_preflight.json", {"plan_sha256": plan["sha256"], "models": models})
    write(root / "execution_started.json", {"plan_sha256": plan["sha256"], "revision": checkout_revision})
    from .traffic import make_trace, trace_document
    seen = set()
    for scenario in plan["body"]["scenarios"]:
        trace_path = scenario["trace_path"]
        if trace_path not in seen:
            cfg = from_sim_dict(scenario["config"])
            write(inside(root, trace_path), trace_document(make_trace(cfg), cfg))
            seen.add(trace_path)
    scenarios = {s["id"]: s for s in plan["body"]["scenarios"]}
    for cell in plan["body"]["cells"]:
        job(root, cell["id"], cell["command"], plan)
        output = inside(root, cell["out"])
        complete = read(output / "complete.json")
        if complete.get("simulation_finished") is not True or complete["result_sha256"] != digest(output / "result.json"):
            raise ValueError("child exited zero without a valid completion record")
        if cell["policy"] == NATIVE_POLICY_NAME:
            native_transport_check(plan, cell, scenarios[cell["scenario"]])
    if plan["schema"] == NATIVE_PLAN_SCHEMA:
        # Transport success is deliberately NOT a scientific suite_finished claim.
        marker = {"schema": "ssn-native-experiment-transport-complete-v1",
                  "transport_finished": True, "runs": len(plan["body"]["cells"]),
                  "plan_sha256": plan["sha256"], "aggregation_supported": False,
                  "plots_supported": False,
                  "scope": "all planned child artifacts transported; scientific verification/aggregation NOT performed"}
        write(root / "execution_complete.json", marker)
        return {"transport_finished": True, "runs": marker["runs"], "aggregation_supported": False}
    write(root / "execution_complete.json", {"suite_finished": True, "runs": len(plan["body"]["cells"]),
                                            "plan_sha256": plan["sha256"]})
    return {"suite_finished": True, "runs": len(plan["body"]["cells"])}


def positive_cli_budget(value):
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise argparse.ArgumentTypeError("TBR budget must be a positive decimal integer")
    return int(value)


def parser():
    root = argparse.ArgumentParser(description="RECONSTRUCTION sweeps; never authors' results")
    commands = root.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="offline: save resolved configs and exact commands; no ML imports")
    planning.add_argument("--suite", required=True)
    planning.add_argument("--out", required=True)
    planning.add_argument("--revision", required=True)
    planning.add_argument("--models", help="JSON mapping N strings to trusted complete run paths")
    planning.add_argument("--baselines-only", action="store_true")
    planning.add_argument("--include-native-tbr", action="store_true", help="opt-in bounded exhaustive transport ONLY")
    planning.add_argument("--tbr-max-nodes", type=positive_cli_budget, default=None,
                          help="native ONLY; independent safety bound (default 12)")
    planning.add_argument("--tbr-max-expansions", type=positive_cli_budget, default=None,
                          help="native ONLY; independent safety bound (default 100000)")
    for command in ("train", "execute"):
        child = commands.add_parser(command, help="executes only when USER invokes; creates local artifacts")
        child.add_argument("--plan", required=True)
        child.add_argument("--revision", required=True)
    aggregate = commands.add_parser("aggregate", help="verify saved genuine runs and paired metrics")
    aggregate.add_argument("--plan", required=True)
    aggregate.add_argument("--out", required=True)
    aggregate.add_argument("--allow-partial", action="store_true")
    aggregate.add_argument("--reference", choices=POLICIES + (NATIVE_POLICY_NAME,), default="TBR_style_hop_oracle")
    plot = commands.add_parser("plot", help="optional lazy matplotlib; labeled reconstruction only")
    plot.add_argument("--summary", required=True)
    plot.add_argument("--out", required=True)
    plot.add_argument("--allow-partial", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "plan":
        result = make_plan(args.suite, args.out, args.revision,
                           read(args.models) if args.models else None, args.baselines_only,
                           include_native_tbr=args.include_native_tbr,
                           tbr_max_nodes=args.tbr_max_nodes, tbr_max_expansions=args.tbr_max_expansions)
    elif args.command == "train":
        result = train_suite(load_plan(args.plan), args.revision)
    elif args.command == "execute":
        result = execute_suite(load_plan(args.plan), args.revision)
    elif args.command == "aggregate":
        from .experiment_results import aggregate_plan
        result = aggregate_plan(load_plan(args.plan), args.out, args.allow_partial, args.reference)
    else:
        from .experiment_plots import plot_summary
        result = plot_summary(args.summary, args.out, args.allow_partial)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
