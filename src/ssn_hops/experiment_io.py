"""Standard-library experiment records; no execution occurs on import."""
import hashlib
import json
from numbers import Integral
from pathlib import Path
import re
import subprocess
import sys
from .config import content_hash, from_dict, require_supported_model
from .sim_config import from_sim_dict

PLAN_SCHEMA = "ssn-experiment-plan-v2"
NATIVE_PLAN_SCHEMA = "ssn-native-exhaustive-experiment-plan-v1"
NATIVE_POLICY_NAME = "TBR_bounded_exhaustive_reference"
NATIVE_RESULT_SCHEMA = "ssn-native-exhaustive-simulation-result-v1"
NATIVE_CONTRACT = {"path": "Repo_Orchestrator_2/tasks/T011-S02-experiment-transport.md",
                   "commit": "5df25ab5514475d4c14acb228aff7044e0103eaf",
                   "blob": "6f5b7b310819c08eac7a42a4453bdddbe85bb9f0",
                   "step": "R3/A09/S02B2A"}


def positive_budget(value, name):
    # Narrow stdlib mirror of accepted adapter validation at245aa27, blob5a554294.
    # NumPy integers are Integral; NumPy bool scalars are not. Never import numpy,
    # torch, simulate or the adapter merely to validate offline safety limits.
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, not bool")
    return int(value)


def native_options(include, max_nodes=None, max_expansions=None):
    if type(include) is not bool:
        raise ValueError("include_native_tbr must be boolean")
    if not include:
        if max_nodes is not None or max_expansions is not None:
            raise ValueError("TBR budgets require explicit native opt-in")
        return None
    nodes = positive_budget(12 if max_nodes is None else max_nodes, "tbr_max_nodes")
    expansions = positive_budget(100000 if max_expansions is None else max_expansions, "tbr_max_expansions")
    return {"policy_identity": NATIVE_POLICY_NAME,
            "search_identity": "bounded_exhaustive_simple_paths_v1",
            "objective": "min_edges_then_lexicographic_full_path",
            "max_nodes": nodes, "max_expansions": expansions,
            "budget_scope": "independent safety controls; NOT author settings",
            "node_preflight_scope": "ALL resolved scenarios before output creation and execution; validation only, no core search",
            "scope": "opt-in planning/execution transport ONLY; scientific aggregation/plots unsupported until separately assigned S02B2B",
            "aggregation_supported": False, "plots_supported": False,
            "authority": "independently specified bounded exhaustive reference; NOT recovered author traversal/code/performance",
            "contract": dict(NATIVE_CONTRACT),
            "core_source_commit": "6df242596c554bb50c04a01eab9599cc54f4c52a",
            "adapter_source_commit": "245aa27a29b629f871ee9d29cf3e6d54c3b24e8a",
            "single_run_source_commit": "1e3c62450ceb68a31ba7a298fdabfbfb015a9f1b"}


def single_run_native_reference(native):
    """Exact frozen single-run declaration, NOT relabeled as aggregated evidence.

    Source: simulate.py at1e3c6245, blob8cc502b4; keep its scope prose unchanged.
    This transport extends orchestration only, not that command's scientific scope.
    """
    return {"policy_identity": NATIVE_POLICY_NAME,
            "search_identity": "bounded_exhaustive_simple_paths_v1",
            "objective": "min_edges_then_lexicographic_full_path",
            "max_nodes": native["max_nodes"], "max_expansions": native["max_expansions"],
            "budget_scope": "independent safety controls; NOT author settings",
            "scope": "opt-in single-run only; existing experiment loaders reject this native result schema; no suite/aggregation/plot integration",
            "node_preflight_scope": "run_single/CLI before output mkdir, including empty traffic; not a policy call; generic Simulator has no command preflight",
            "route_timing_scope": "whole choose call including adapter, core validation/search and counters; excludes context/masks; NOT pure core cost or author/Fig.5 equivalence",
            "authority": "independently specified bounded exhaustive reference; NOT recovered author traversal/code/performance",
            "contract": {"path": "Repo_Orchestrator_2/tasks/T011-S02-native-command.md",
                         "commit": "aae9530aa612972b77a854e893c0c02205288f52",
                         "blob": "b931d916a869d369ca9c2063270bead4dcaf20bf",
                         "step": "R3/A08/S02B1B"},
            "core_source_commit": "6df242596c554bb50c04a01eab9599cc54f4c52a",
            "adapter_source_commit": "245aa27a29b629f871ee9d29cf3e6d54c3b24e8a"}


def read(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def revision(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("revision must be the actual lowercase 40-character checkout SHA")
    return value


def source_hashes():
    return {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def inside(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("artifact paths must be relative without parent traversal")
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("artifact path escapes the output root")
    return path


def schema_guard(plan):
    if plan.get("schema") not in (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA):
        raise ValueError("unsupported plan schema; v1 plans/results must be regenerated for the T022-S01 input contract")
    if plan["schema"] == PLAN_SCHEMA:
        body = plan.get("body", {})
        if ("native_reference" in body or "resolved_templates" in body
                or NATIVE_POLICY_NAME in body.get("policies", [])
                or any(c.get("policy") == NATIVE_POLICY_NAME
                       or "--tbr-max-nodes" in c.get("command", [])
                       or "--tbr-max-expansions" in c.get("command", [])
                       for c in body.get("cells", []))):
            raise ValueError("native plans require the isolated native schema, not legacy v2")


def validate_native_plan(plan):
    """Reconstruct every resolved scenario and exact argv; no execution/import ML.

    Hashes detect accidental mismatch, not deliberate forgery of all inputs.
    Saved resolved templates avoid rereading movable original suite/template paths.
    """
    from .experiments import (CONTRACT, FEATURE_CONTRACT, POLICIES, merge,
                              plan_commands, resolve_plan_inputs, validate_suite)
    body = plan["body"]
    required = {"suite", "revision", "root", "contract", "feature_contract", "mode", "source_sha256",
                "policies", "models", "scenarios", "cells", "offline_steps", "file_sha256",
                "execution", "native_reference", "resolved_templates"}
    if set(body) != required:
        raise ValueError("native plan fields mismatch")
    native = body["native_reference"]
    expected_native = native_options(True, native["max_nodes"], native["max_expansions"])
    if content_hash(native) != content_hash(expected_native):
        raise ValueError("native plan metadata mismatch")
    if body["mode"] not in ("baselines_only", "with_trained_GLR"):
        raise ValueError("native plan mode mismatch")
    baselines_only = body["mode"] == "baselines_only"
    policies = list(POLICIES[1:] if baselines_only else POLICIES) + [NATIVE_POLICY_NAME]
    if body["policies"] != policies:
        raise ValueError("native plan policy order/set mismatch")
    if (body["contract"] != CONTRACT or body["feature_contract"] != FEATURE_CONTRACT
            or body["execution"] != "sequential user invocation only; no resume/overwrite"):
        raise ValueError("native plan contract/execution mismatch")
    root = Path(body["root"]).resolve()
    if str(root) != body["root"]:
        raise ValueError("native plan root must be canonical and absolute")
    templates = body["resolved_templates"]
    if set(templates) != {"core", "simulation"}:
        raise ValueError("native resolved template fields mismatch")
    core = from_dict(templates["core"])
    sim = from_sim_dict(templates["simulation"])
    if core.to_dict() != templates["core"] or sim.to_dict() != templates["simulation"]:
        raise ValueError("native templates must be fully resolved")
    suite = body["suite"]
    if "policy_scope" in suite:
        # T057-S01: the native plan schema is frozen; the optional suite key is rejected here.
        raise ValueError("native plans do not support policy_scope")
    validate_suite(suite, core, sim)
    if (merge(core.to_dict(), suite["training_overrides"]) != core.to_dict()
            or merge(sim.to_dict(), suite["simulation_overrides"]) != sim.to_dict()):
        raise ValueError("native resolved templates disagree with suite overrides")
    if not baselines_only:
        # Mode-agnostic: topology-only (default) and the optional delay extension are both valid.
        require_supported_model(core.model)
    supplied = {}
    for n, item in body["models"].items():
        if not isinstance(n, str) or not n.isdigit() or type(item["supplied"]) is not bool:
            raise ValueError("native model mapping mismatch")
        if not isinstance(item["run"], str):
            raise ValueError("native model run path mismatch")
        if item["supplied"]:
            supplied[n] = item["run"]
    training, scenarios = resolve_plan_inputs(suite, core, sim, root, supplied, baselines_only, expected_native)
    commands, cells = plan_commands(root, training, scenarios, policies, body["revision"], expected_native)
    # Canonical hashes also distinguish booleans/floats from integer metadata.
    for label, expected in (("models", training), ("scenarios", scenarios),
                            ("offline_steps", commands), ("cells", cells)):
        if content_hash(body[label]) != content_hash(expected):
            raise ValueError(f"native resolved {label}/command mismatch")
    configurations = {item["config_path"]: item["config"] for item in [*training.values(), *scenarios]}
    if set(body["file_sha256"]) != set(configurations):
        raise ValueError("native configuration file hash map mismatch")
    for relative, expected in configurations.items():
        if content_hash(read(inside(root, relative))) != content_hash(expected):
            raise ValueError("native saved config differs from resolved scenario/model")


def check_scoped_plan(document):
    """T057-S01 (R8, P-2): extra checks for plans whose scenarios declare ``policies``.

    Called by validate_plan ONLY when at least one scenario has the field (policy_scope plans);
    legacy plans never reach it. Rules (all-or-none): every scenario declares a nonempty list of
    distinct known policies in canonical POLICIES order (the native policy is not allowed);
    body['policies'] equals the union of those lists in canonical order (hence a superset of each);
    the cells equal, in order, scenarios x their declared policies with ids '<scenario>--<policy>';
    native-schema plans are rejected. Cell commands/out paths are not re-derived here (as for legacy plans).
    """
    from .experiments import POLICIES
    body = document["body"]
    if document["schema"] == NATIVE_PLAN_SCHEMA:
        raise ValueError("native plans do not support policy_scope")
    scenarios = body["scenarios"]
    if not all("policies" in s for s in scenarios):
        raise ValueError("scoped plan: every scenario must declare policies (mixed plans are rejected)")
    rank = {policy: i for i, policy in enumerate(POLICIES)}
    union = set()
    for scenario in scenarios:
        declared = scenario["policies"]
        if (not isinstance(declared, list) or not declared
                or any(not isinstance(p, str) or p not in rank for p in declared)
                or [rank[p] for p in declared] != sorted({rank[p] for p in declared})):
            raise ValueError("scoped plan: scenario policies must be a nonempty canonical-order "
                             "list of distinct known policies")
        union.update(declared)
    if body["policies"] != [p for p in POLICIES if p in union]:
        raise ValueError("scoped plan: body policies differ from the union of scenario policies "
                         "in canonical order")
    expected = [(s["id"] + "--" + p, s["id"], p) for s in scenarios for p in s["policies"]]
    actual = [(c["id"], c["scenario"], c["policy"]) for c in body["cells"]]
    if actual != expected:
        raise ValueError("scoped plan: cells differ from scenarios x their declared policies")


def validate_plan(document, expected_root=None):
    if set(document) != {"schema", "body", "sha256"}:
        raise ValueError("unsupported plan fields")
    schema_guard(document)
    body = document["body"]
    if content_hash(body) != document["sha256"]:
        raise ValueError("plan content hash mismatch")
    revision(body["revision"])
    root = Path(body["root"]).resolve()
    if expected_root is not None and root != Path(expected_root).resolve():
        raise ValueError("plan moved: absolute commands require a fresh plan")
    for name, expected in body["file_sha256"].items():
        if digest(inside(root, name)) != expected:
            raise ValueError(f"planned file hash mismatch: {name}")
    for cell in body["cells"]:
        inside(root, cell["out"])
        inside(root, cell["config_path"])
    for scenario in body["scenarios"]:
        inside(root, scenario["trace_path"])
    if len({c["id"] for c in body["cells"]}) != len(body["cells"]):
        raise ValueError("duplicate plan cell")
    if any("policies" in s for s in body["scenarios"]):
        check_scoped_plan(document)
    if document["schema"] == NATIVE_PLAN_SCHEMA:
        try:
            validate_native_plan(document)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("malformed native plan") from exc
    return document


def load_plan(path):
    path = Path(path).resolve()
    return validate_plan(read(path), path.parent)


def execution_guard(plan, supplied_revision):
    schema_guard(plan)
    if plan["schema"] == NATIVE_PLAN_SCHEMA:
        # Direct API execution gets the same hash/path/config/bounds/argv preflight.
        validate_plan(plan)
    if revision(supplied_revision) != plan["body"]["revision"]:
        raise ValueError("execution revision differs from planned revision")
    if source_hashes() != plan["body"]["source_sha256"]:
        raise ValueError("source files changed since planning; create a new plan")


def native_transport_check(plan, cell, scenario):
    """Envelope/hash/identity checks ONLY. No scientific counters or aggregation."""
    root = Path(plan["body"]["root"])
    output = inside(root, cell["out"])
    complete = read(output / "complete.json")
    if complete.get("simulation_finished") is not True or complete.get("result_sha256") != digest(output / "result.json"):
        raise ValueError("native completion/hash mismatch")
    result = read(output / "result.json")
    reference = single_run_native_reference(plan["body"]["native_reference"])
    if result.get("schema") != NATIVE_RESULT_SCHEMA or result.get("policy") != NATIVE_POLICY_NAME:
        raise ValueError("native result schema/policy mismatch")
    if content_hash(result.get("native_reference")) != content_hash(reference):
        raise ValueError("native result limits/metadata mismatch")
    details = result.get("policy_details", {})
    for key in ("policy_identity", "search_identity", "objective", "max_nodes", "max_expansions"):
        if content_hash(details.get(key)) != content_hash(reference[key]):
            raise ValueError("native policy details identity/limits mismatch")
    if result.get("declared_checkout_revision") != plan["body"]["revision"]:
        raise ValueError("native result revision mismatch")
    expected_files = {"config.json", "traffic.json", "provenance.json", "packets.json", "events.jsonl"}
    hashes = result.get("output_sha256", {})
    if set(hashes) != expected_files:
        raise ValueError("native result artifact hash map mismatch")
    for filename, expected in hashes.items():
        if digest(output / filename) != expected:
            raise ValueError(f"native result artifact hash mismatch: {filename}")
    if (content_hash(read(output / "config.json")) != content_hash(scenario["config"])
            or result.get("config_sha256") != scenario["config_sha256"]):
        raise ValueError("native result configuration mismatch")
    trace = read(inside(root, scenario["trace_path"]))
    if read(output / "traffic.json") != trace or result.get("traffic_sha256") != trace["sha256"]:
        raise ValueError("native result paired trace mismatch")
    origin = read(output / "provenance.json")
    if (origin.get("declared_checkout_revision") != plan["body"]["revision"]
            or origin.get("source_sha256") != plan["body"]["source_sha256"]
            or content_hash(origin.get("native_reference")) != content_hash(reference)):
        raise ValueError("native provenance identity/source/revision mismatch")
    expected_inputs = {str(root / cell["config_path"]): digest(root / cell["config_path"]),
                       str(root / scenario["trace_path"]): digest(root / scenario["trace_path"])}
    if origin.get("input_file_sha256") != expected_inputs:
        raise ValueError("native provenance input hashes mismatch")


def job(root, job_id, command, plan):
    """User-invoked subprocess, argv only, no shell; exclusive logs/status."""
    root = Path(root)
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    prefix = logs / job_id
    argv = [sys.executable, *command[1:]]
    record = {"id": job_id, "argv": argv, "cwd": str(Path.cwd()),
              "revision": plan["body"]["revision"], "plan_sha256": plan["sha256"]}
    write(str(prefix) + ".started.json", record)
    try:
        with Path(str(prefix) + ".stdout.txt").open("x", encoding="utf-8") as stdout:
            with Path(str(prefix) + ".stderr.txt").open("x", encoding="utf-8") as stderr:
                completed = subprocess.run(argv, stdout=stdout, stderr=stderr, check=False)
        record.update({"exit_code": completed.returncode, "exception": None})
    except Exception as exc:
        record.update({"exit_code": None, "exception": f"{type(exc).__name__}: {exc}"})
        write(str(prefix) + ".status.json", record)
        raise
    record["log_sha256"] = {suffix: digest(str(prefix) + suffix)
                            for suffix in (".stdout.txt", ".stderr.txt")}
    write(str(prefix) + ".status.json", record)
    if completed.returncode != 0:
        raise RuntimeError(f"{job_id} exited {completed.returncode}; preserve {prefix} logs")
    return record
