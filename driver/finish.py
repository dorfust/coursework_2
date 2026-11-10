"""finish: model_preflight.json and the completion marker execution_complete.json, plus a read-only check. Written, NOT run.

Mirrored contract (experiments.execute_suite / preflight_models, blob 72b6fa02; experiment_results.verify_models /
verify_cell / aggregate_plan, blob ba5576ef):
  preflight: models = experiments.preflight_models(plan) (CALLED, not copied; loads every trained model through
             training.load_trained_model and compares with check_model and feature_spec) and the file
             model_preflight.json = {'plan_sha256': plan['sha256'], 'models': models}, written like experiment_io.write.
             Needs ALL models of the plan to be complete; afterwards experiment_results.verify_models(plan) is called
             as post-check (when it fails, a file written by THIS call is removed again).
  marker:    execution_complete.json = {'suite_finished': True, 'runs': len(body['cells']), 'plan_sha256': plan['sha256']}
             (the form aggregate_plan checks). Written ONLY when every DECLARED cell (147 suite_m1, 135 suite_m1_nocgr) is
             verified by experiment_results.verify_cell with the records of verify_models; never for a partial set.
  check:     read-only report, writes nothing. Key `preflight_check_level` is 'light' (default: no model is loaded,
             `preflight_would_succeed` only says that every model has complete.json and best.pt) or 'deep' (--deep: the
             project's preflight_models was called).
Both files are created exclusively (temp file + hard link, like traces.py): an existing file with identical content is
'already_done'; different content is never overwritten (exit 4). Legacy plan schema only (native plans refused).
File system problems of that step (a stale temp file `<name>.tmp<pid>` of an earlier crashed call, a write error, a file
system without hard links) raise FinishIOError (a FinishConflict): one line `refused: ...`, exit 4, no traceback,
nothing created (a stale temp file is never deleted by this tool).

CLI (from the m1 directory; preflight needs torch and reads the trained models; marker reads every declared cell):
  python -m driver.finish preflight --plan <root>/plan.json --revision <sha>
  python -m driver.finish marker    --plan <root>/plan.json --revision <sha>
  python -m driver.finish check     --plan <root>/plan.json [--revision <sha>] [--deep]
Exit codes: 0 ok / already done / check report printed, 3 precondition not met (not ready), 4 conflict, file system
problem or usage, 5 post-check failed.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from ssn_hops import experiment_io as eio
from . import plan_io, run_cell

EXIT_OK, EXIT_NOT_READY, EXIT_REFUSED, EXIT_POSTCHECK = 0, 3, 4, 5
PREFLIGHT, MARKER = "model_preflight.json", "execution_complete.json"


class FinishRefused(RuntimeError):
    """A precondition is not met (models missing, cells not verified): nothing was written."""


class FinishConflict(RuntimeError):
    """The target file exists with different content (or unreadable): never overwritten."""


class FinishIOError(FinishConflict):
    """A file system problem while creating the target (stale temp file, write error, no hard links): exit 4."""


class PostCheckFailed(RuntimeError):
    """The aggregator's own check rejected what was just produced."""


def create_exact(path, content):
    """Exclusive create of a JSON file written by experiment_io.write; returns 'written' or 'already_done'."""
    path = Path(path)
    wanted = json.loads(json.dumps(content, sort_keys=True, allow_nan=False))
    if path.exists():
        try:
            existing = eio.read(path)
        except Exception as exc:
            raise FinishConflict(f"{path.name} exists and is unreadable ({exc}); not touching it") from exc
        if existing == wanted:
            return "already_done"
        raise FinishConflict(f"{path.name} exists with different content; refusing to overwrite")
    temp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        eio.write(temp, wanted)
    except FileExistsError as exc:
        raise FinishIOError(f"stale temp file {temp.name} exists (left by an earlier crashed call with the same pid); "
                            "make sure no other finish call is running, delete it by hand and rerun") from exc
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise FinishIOError(f"cannot write {temp.name} ({type(exc).__name__}: {exc})") from exc
    try:
        os.link(temp, path)
    except FileExistsError:
        return create_exact(path, content)      # lost a race: compare with the file that won
    except OSError as exc:
        raise FinishIOError(f"cannot create {path.name} by hard link ({type(exc).__name__}: {exc}); the work directory "
                            "must be on a file system that supports hard links") from exc
    finally:
        temp.unlink()
    return "written"


def models_light(view):
    """(complete N list, {N: reason}) by a cheap torch-free look (complete.json + best.pt); NOT the project's check."""
    complete, missing = [], {}
    for n, item in view.body["models"].items():
        run = Path(item["run"])
        try:
            finished = eio.read(run / "complete.json").get("training_finished") is True
        except Exception:
            finished = False
        if finished and (run / "best.pt").exists():
            complete.append(n)
        else:
            missing[n] = "run is not complete (complete.json/best.pt missing)"
    return complete, missing


def diagnose_models(view):
    from ssn_hops import experiments
    out = {}
    for n, item in view.body["models"].items():
        body = dict(view.body)
        body["models"] = {n: item}
        try:
            experiments.preflight_models({"body": body})
            out[n] = "ok"
        except Exception as exc:
            out[n] = f"{type(exc).__name__}: {exc}"
    return out


def compute_preflight(view):
    """models = experiments.preflight_models(plan) (the project's own function; raises when any model is unusable)."""
    from ssn_hops import experiments
    try:
        return experiments.preflight_models(view.plan)
    except Exception as exc:
        raise FinishRefused(f"preflight_models failed ({type(exc).__name__}: {exc}); per model: "
                            f"{diagnose_models(view)}") from exc


def preflight_document(view, models):
    return {"plan_sha256": view.plan["sha256"], "models": models}


def marker_document(view):
    return {"suite_finished": True, "runs": len(view.body["cells"]), "plan_sha256": view.plan["sha256"]}


def _legacy_only(view):
    if view.plan["schema"] != eio.PLAN_SCHEMA:
        raise FinishRefused("only legacy ssn-experiment-plan-v2 suite plans are supported (native plans refused)")


def do_preflight(view):
    _legacy_only(view)
    _, missing = models_light(view)
    if missing:
        raise FinishRefused(f"preflight needs ALL trained models of the plan; not complete: {missing}")
    models = compute_preflight(view)
    target = view.root / PREFLIGHT
    status = create_exact(target, preflight_document(view, models))
    from ssn_hops import experiment_results as results
    try:
        results.verify_models(view.plan)
    except Exception as exc:
        if status == "written":
            target.unlink()
        raise PostCheckFailed(f"verify_models rejected the preflight ({type(exc).__name__}: {exc})"
                              + ("; the file written by this call was removed" if status == "written" else "")) from exc
    return {"mode": "preflight", "status": status, "path": str(target), "models": sorted(models)}


def verify_cells(view, strict):
    """(verified ids, missing ids, {id: error}). strict: verify_cell with verify_models records (the aggregator's own);
    not strict (no usable model_preflight.json yet): run_cell.resume_verifier (W1a, weaker for GLR cells)."""
    from ssn_hops import experiment_results as results
    records = results.verify_models(view.plan) if strict else None
    verified, missing, errors = [], [], {}
    for cell in view.cells:
        try:
            if strict:
                value = results.verify_cell(view.plan, cell, view.scenario_of(cell), records)
            else:
                value = run_cell.resume_verifier(view, cell)
        except Exception as exc:
            value = None
            errors[cell["id"]] = f"{type(exc).__name__}: {exc}"
        (verified if value is not None else missing).append(cell["id"])
    return verified, missing, errors


def do_marker(view):
    _legacy_only(view)
    if "GLR" in view.body["policies"] and not (view.root / PREFLIGHT).exists():
        raise FinishRefused("model_preflight.json is missing: run `finish preflight` first")
    try:
        verified, missing, errors = verify_cells(view, strict=True)
    except Exception as exc:
        raise FinishRefused(f"verify_models failed ({type(exc).__name__}: {exc})") from exc
    if missing:
        first = {c: errors.get(c) for c in missing[:5]}
        raise FinishRefused(f"{len(missing)} of {len(view.cells)} declared cells are not verified (no marker for a "
                            f"partial set); first: {first}")
    status = create_exact(view.root / MARKER, marker_document(view))
    return {"mode": "marker", "status": status, "path": str(view.root / MARKER), "runs": len(view.cells)}


def _file_state(path, expected):
    path = Path(path)
    if not path.exists():
        return {"present": False, "matches": None}
    try:
        return {"present": True, "matches": eio.read(path) == json.loads(json.dumps(expected))}
    except Exception as exc:
        return {"present": True, "matches": False, "error": f"{type(exc).__name__}: {exc}"}


def check_report(view, deep=False, cell_result=None):
    """Read-only: what exists and what `finish preflight` / `finish marker` would do. cell_result = verify_cells output."""
    complete, missing_models = models_light(view)
    report = {"plan_sha256": view.sha256, "declared_cells": len(view.cells),
              "models_complete_light": complete, "models_missing": missing_models,
              "preflight_check_level": "deep" if deep else "light"}
    preflight = {"present": (view.root / PREFLIGHT).exists(), "valid": None}
    expected_models = None
    if not missing_models and deep:
        try:
            expected_models = compute_preflight(view)
        except Exception as exc:
            report["preflight_deep_error"] = f"{type(exc).__name__}: {exc}"
    if preflight["present"]:
        from ssn_hops import experiment_results as results
        try:
            results.verify_models(view.plan)
            preflight["valid"] = True
        except Exception as exc:
            preflight.update({"valid": False, "error": f"{type(exc).__name__}: {exc}"})
        if expected_models is not None:
            preflight["matches_recomputed"] = _file_state(view.root / PREFLIGHT,
                                                           preflight_document(view, expected_models))["matches"]
    report["model_preflight"] = preflight
    report["preflight_would_succeed"] = (not missing_models and "preflight_deep_error" not in report) or bool(
        preflight["valid"])
    strict = bool(preflight["valid"]) or "GLR" not in view.body["policies"]
    verified, missing, errors = cell_result if cell_result is not None else verify_cells(view, strict=strict)
    report.update({"cells_verified": len(verified), "cells_missing": len(missing),
                   "cells_verification": "strict (verify_cell)" if strict else "resume (no valid model_preflight.json)",
                   "first_missing": missing[:5], "first_errors": {c: errors[c] for c in list(errors)[:3]}})
    marker = _file_state(view.root / MARKER, marker_document(view))
    report["marker"] = marker
    report["marker_would_succeed"] = bool(strict and not missing and view.plan["schema"] == eio.PLAN_SCHEMA)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="finish a staged M1 root: model_preflight.json, marker, check")
    parser.add_argument("mode", choices=("preflight", "marker", "check"))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--deep", action="store_true", help="check: also load the models (needs torch)")
    args = parser.parse_args(argv)
    if args.mode != "check" and not args.revision:
        print("refused: --revision is required for preflight and marker")
        return EXIT_REFUSED
    try:
        view = (plan_io.load_for_execution(args.plan, args.revision, expected_plan_sha256=args.plan_sha256)
                if args.revision else plan_io.load_readonly(args.plan))
    except Exception as exc:
        print(f"refused: {type(exc).__name__}: {exc}")
        return EXIT_REFUSED
    try:
        if args.mode == "check":
            print(json.dumps(check_report(view, deep=args.deep), indent=1, sort_keys=True))
            return EXIT_OK
        result = do_preflight(view) if args.mode == "preflight" else do_marker(view)
    except FinishRefused as exc:
        print(f"not ready: {exc}")
        return EXIT_NOT_READY
    except FinishConflict as exc:
        print(f"refused: {exc}")
        return EXIT_REFUSED
    except PostCheckFailed as exc:
        print(f"post-check failed: {exc}")
        return EXIT_POSTCHECK
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
