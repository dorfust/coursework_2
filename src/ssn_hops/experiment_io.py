"""Standard-library experiment records; no execution occurs on import."""
# Contents: schema names; native and enumeration plan metadata; JSON read, write and digest; the path guard
# (inside); plan validation (legacy, scoped, enumeration, native); execution_guard; job, which starts a child
# process only when it is called. Imports: the standard library plus .config and .sim_config of this
# package (their own imports are not listed here).
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
# T125: optional TBR_enumeration policy. This module is stdlib-only, so the name, the search
# identity and the default budgets are DUPLICATED here from tbr_enum.py; verify_enum_counters
# (experiment_results) compares the budgets and identity of every saved cell with the plan.
ENUM_POLICY_NAME = "TBR_enumeration"
ENUM_SEARCH_IDENTITY = "iterative_deepening_full_enumeration_v1"
# Budgets count expansions; one expansion is one search prefix entered (see tbr_enum.py). CALL limits one
# policy call: an incomplete call returns None and the packet waits. CELL limits the cumulative expansions
# of one policy instance, i.e. one simulation cell: afterwards every call is skipped. The default CELL
# value is 1000 times the default CALL value. Both are safety controls, not paper settings.
ENUM_DEFAULT_MAX_CALL_EXPANSIONS = 200000
ENUM_DEFAULT_MAX_CELL_EXPANSIONS = 200000000
ENUM_FLAGS = ("--enum-max-call-expansions", "--enum-max-cell-expansions")


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
    # 12 is the default max_nodes (planning raises for a resolved N above max_nodes, see resolve_plan_inputs
    # in experiments.py); 100000 is the default max_expansions. validate_native_plan compares the whole
    # returned mapping, strings included, by content hash with a re-derived copy, so an edit of any value
    # here makes saved native plans fail that check.
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


def enum_options(include, max_call=None, max_cell=None):
    """T125: metadata of the optional TBR_enumeration plan option, or None when it is off.

    Budgets without the opt-in are an error (mirrors native_options). The returned mapping is
    stored as body['tbr_enumeration'] and re-derived by check_enum_plan.
    """
    if type(include) is not bool:
        raise ValueError("include_tbr_enumeration must be boolean")
    if not include:
        if max_call is not None or max_cell is not None:
            raise ValueError("enumeration budgets require explicit opt-in (include_tbr_enumeration)")
        return None
    calls = positive_budget(ENUM_DEFAULT_MAX_CALL_EXPANSIONS if max_call is None else max_call,
                            "enum_max_call_expansions")
    cells = positive_budget(ENUM_DEFAULT_MAX_CELL_EXPANSIONS if max_cell is None else max_cell,
                            "enum_max_cell_expansions")
    return {"policy_identity": ENUM_POLICY_NAME,
            "search_identity": ENUM_SEARCH_IDENTITY,
            "objective": "min_edges_then_lexicographic_full_path",
            "max_call_expansions": calls, "max_cell_expansions": cells,
            "budget_scope": "independent safety controls; NOT paper settings",
            "incomplete_rule": "an incomplete or skipped call returns None (the packet waits); never a route from partial work; never a fallback router",
            "scope": "optional second run; incomplete searches are allowed and reported (completeness_share); the plan keeps the legacy plan schema",
            "authority": "independently specified iterative-deepening enumeration; NOT the paper's brute force"}


# The keys and text mirror the native_reference mapping that run_single in simulate.py builds (same 13 keys;
# the values of search_identity and objective are imported there and are not compared here).
# native_transport_check compares content hashes of the saved mappings with this one, so a difference
# between the two copies makes that check raise.
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
    """Write value as JSON to a new file, creating the parent folders.

    The file is opened with mode x (exclusive creation); this is where the pipeline's no-overwrite rule
    is applied. json.dump is called with indent=2, sort_keys=True and allow_nan=False, then a newline is
    written. The JSON goes directly into that file: no temporary file and no rename are used.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


# sha256 hex digest of the file, read in blocks of 1024 * 1024 bytes.
def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def revision(value):
    # Format check only: 40 lowercase hex characters. The value is not compared with any repository here;
    # execution_guard compares it with the revision stored in the plan.
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("revision must be the actual lowercase 40-character checkout SHA")
    return value


def source_hashes():
    """sha256 of every *.py file in the folder of this module, as {file name: hex digest}.

    The glob pattern is *.py (no recursive pattern is used). make_plan stores the result as
    body['source_sha256']; execution_guard (called by train_suite and execute_suite) compares the current
    result with that stored copy and raises ValueError if they differ. So any later change to any *.py
    file of the package, a comment-only edit included, or an added or removed *.py file, makes
    execution_guard raise, and the plan has to be made again. The folder is taken from __file__ of this
    module.
    """
    return {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def inside(root, relative):
    """Return (root / relative).resolve() for a relative path that stays inside the root.

    Raises ValueError for an absolute path, for any '..' part, and when the resolved path is not under
    the resolved root.
    """
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("artifact paths must be relative without parent traversal")
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("artifact path escapes the output root")
    return path


def schema_guard(plan):
    """Refuse unknown plan schemas and legacy-schema plans that carry native markers.

    Only PLAN_SCHEMA and NATIVE_PLAN_SCHEMA are accepted. A PLAN_SCHEMA plan is refused if its body has
    native_reference or resolved_templates, lists the native policy name in policies or in a cell, or has
    --tbr-max-nodes or --tbr-max-expansions in a cell command. Enumeration markers are not refused here
    (see check_enum_plan).
    """
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
    # Imported inside the function: experiments.py imports this module at its top level.
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
    distinct known policies in canonical POLICIES order (the native policy is not allowed;
    T125: the optional TBR_enumeration policy is known and ranks after POLICIES);
    body['policies'] equals the union of those lists in canonical order (hence a superset of each);
    the cells equal, in order, scenarios x their declared policies with ids '<scenario>--<policy>';
    native-schema plans are rejected. Cell commands/out paths are not re-derived here (as for legacy plans).
    """
    # Imported inside the function: experiments.py imports this module at its top level.
    from .experiments import POLICIES
    ordered = POLICIES + (ENUM_POLICY_NAME,)
    body = document["body"]
    if document["schema"] == NATIVE_PLAN_SCHEMA:
        raise ValueError("native plans do not support policy_scope")
    scenarios = body["scenarios"]
    if not all("policies" in s for s in scenarios):
        raise ValueError("scoped plan: every scenario must declare policies (mixed plans are rejected)")
    rank = {policy: i for i, policy in enumerate(ordered)}
    union = set()
    for scenario in scenarios:
        declared = scenario["policies"]
        if (not isinstance(declared, list) or not declared
                or any(not isinstance(p, str) or p not in rank for p in declared)
                or [rank[p] for p in declared] != sorted({rank[p] for p in declared})):
            raise ValueError("scoped plan: scenario policies must be a nonempty canonical-order "
                             "list of distinct known policies")
        union.update(declared)
    if body["policies"] != [p for p in ordered if p in union]:
        raise ValueError("scoped plan: body policies differ from the union of scenario policies "
                         "in canonical order")
    expected = [(s["id"] + "--" + p, s["id"], p) for s in scenarios for p in s["policies"]]
    actual = [(c["id"], c["scenario"], c["policy"]) for c in body["cells"]]
    if actual != expected:
        raise ValueError("scoped plan: cells differ from scenarios x their declared policies")


def check_enum_plan(body):
    """T125: plans that carry the optional TBR_enumeration policy; any other plan: nothing is checked.

    A plan 'carries' it when the policy name, the body key tbr_enumeration or an enumeration
    flag in a cell command is present. Then: the metadata equals enum_options(...) of its own
    budgets; the policy is listed; every scenario has exactly one enumeration cell; every
    enumeration cell command holds both flags with the planned values; no other cell holds them.
    """
    # The expected budgets are taken from the plan's own body["tbr_enumeration"], so this check shows that
    # the metadata, the policy list and the cell commands agree with each other, not that the budgets equal
    # the defaults. A flag is checked through the token right after its first occurrence in the command.
    cells = body.get("cells", [])
    used = (ENUM_POLICY_NAME in body.get("policies", []) or "tbr_enumeration" in body
            or any(c.get("policy") == ENUM_POLICY_NAME
                   or any(flag in c.get("command", []) for flag in ENUM_FLAGS) for c in cells))
    if not used:
        return
    try:
        given = body["tbr_enumeration"]
        expected = enum_options(True, given["max_call_expansions"], given["max_cell_expansions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed TBR_enumeration plan options") from exc
    if content_hash(given) != content_hash(expected):
        raise ValueError("TBR_enumeration plan metadata mismatch")
    if ENUM_POLICY_NAME not in body.get("policies", []):
        raise ValueError("TBR_enumeration plan options without the policy in the policy list")
    values = (str(expected["max_call_expansions"]), str(expected["max_cell_expansions"]))
    enum_cells = 0
    for cell in cells:
        command = cell["command"]
        if cell["policy"] == ENUM_POLICY_NAME:
            enum_cells += 1
            for flag, value in zip(ENUM_FLAGS, values):
                if flag not in command or command[command.index(flag) + 1:command.index(flag) + 2] != [value]:
                    raise ValueError("TBR_enumeration cell command lacks the planned budget flags")
        elif any(flag in command for flag in ENUM_FLAGS):
            raise ValueError("enumeration budget flags in a cell of another policy")
    if enum_cells != len(body["scenarios"]):
        raise ValueError("TBR_enumeration plan needs one enumeration cell per scenario")


def validate_plan(document, expected_root=None):
    """Structural and hash checks of a saved plan; returns the document or raises.

    Order: keys schema, body, sha256; schema_guard; content_hash(body) equals sha256; revision format;
    the recorded root equals expected_root if given (a moved plan is refused); sha256 of every file
    listed in body['file_sha256'] (the saved configs); cell, config and trace paths stay inside the
    root; unique cell ids; check_scoped_plan if any scenario has policies; check_enum_plan;
    validate_native_plan for the native schema, where KeyError, TypeError, AttributeError and
    OverflowError become ValueError.
    """
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
        inside(root, trace_path_placeholder := scenario["trace_path"])
    if len({c["id"] for c in body["cells"]}) != len(body["cells"]):
        raise ValueError("duplicate plan cell")
    if any("policies" in s for s in body["scenarios"]):
        check_scoped_plan(document)
    check_enum_plan(body)
    if document["schema"] == NATIVE_PLAN_SCHEMA:
        try:
            validate_native_plan(document)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("malformed native plan") from exc
    return document


def load_plan(path):
    """Read a plan file and validate it with the folder of that file as expected_root."""
    path = Path(path).resolve()
    return validate_plan(read(path), path.parent)


def execution_guard(plan, supplied_revision):
    """Preconditions of train_suite and execute_suite; writes nothing; raises ValueError.

    Order: schema_guard; validate_plan(plan) if the plan has the native schema; the supplied revision
    (40 lowercase hex characters) equals body['revision']; source_hashes() equals body['source_sha256'].
    """
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
    # expected_files are the five names that run_single in simulate.py puts into output_sha256; result.json
    # and complete.json are not among them (result.json and complete.json are read and compared above).
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


# Details: argv is [sys.executable] plus command[1:] (command[0], the literal "python" of the planned
# commands, is ignored); no shell; the working directory is that of the current process (recorded as cwd).
# Files in <root>/logs: <id>.started.json before the run; <id>.stdout.txt and <id>.stderr.txt (opened with
# mode x); <id>.status.json after the run, with the exit code and the sha256 of both logs. The child's
# stdout and stderr go to those files, not to the console. A nonzero exit code writes status.json and then
# raises RuntimeError; an exception while starting is recorded in status.json (exit_code None) and re-raised.
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
