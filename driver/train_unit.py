"""Training unit: the plan's training steps of ONE N, in plan order (data, train, evaluate). Written, NOT run.

Structure taken from experiments.train_suite / plan_commands (blob 72b6fa02): body['models'][N]['steps'] =
[data-nN (generate), train-nN, evaluate-nN] with the exact argv of the plan; train_suite runs them through
experiment_io.job(); this unit runs them through run_cell._spawn_and_wait (same logs/<id>.started|stdout|stderr|status
records as job(), plus a wall-clock cap with process-group kill).

Semantics mirrored from train_suite: generate refuses an existing data directory and train() refuses an existing run
directory (no resume), so a unit whose artifacts exist in an incomplete state is REFUSED unless discard=True; a unit
whose run directory passes the project's own completeness check (experiments.preflight_models restricted to this N:
training.load_trained_model + check_model + feature_spec comparison, i.e. the check used by preflight_models) and whose
evaluate output exists (and is readable JSON) is SKIPPED. A run that passes the check but has no evaluate output
(killed during evaluate), or whose test.json is torn/unreadable (F-5), runs only the evaluate step: with discard=True
ONLY the evaluation artifacts (test.json and the evaluate logs) are removed first; a training that passes the project
check is never deleted. Only a run that FAILS the project check is discarded as a whole (data, run, test.json, logs of
this N). Models supplied through plan --models (item['supplied']) are never trained: train_suite skips them
without checking; this unit additionally verifies them with the same check.
Not mirrored (not read by the aggregator): training_started.json / training_complete.json of train_suite.

A-4 (T063): a project check that CANNOT RUN is not evidence of a damaged run. If the check raises ImportError (for
example torch is not installed in this environment) or an OSError that signals I/O trouble (PermissionError, EIO,
ENOSPC ...), classify returns 'check_unavailable' and run_train_unit REFUSES the unit even with discard=True (message
names the exception and says that the check could not run; ledger `refused` event with reason
project_check_could_not_run; exit 4); nothing is deleted. A genuine damaged run (ValueError, KeyError, RuntimeError,
...) keeps the earlier behaviour: 'incomplete', deletable by discard. DEVIATION from the literal wording 'OSError':
FileNotFoundError, NotADirectoryError and IsADirectoryError are NOT treated as 'check unavailable' because they
describe the layout of a damaged run (a run killed before best.pt exists makes the project's loader raise
FileNotFoundError); treating them as unavailable would make --discard useless for exactly the run it exists for.

Per-unit cap: parameter train_cap_minutes (slices.json 'parameters', default 120), wall clock over all steps of the
unit; on expiry the process group of the running step is SIGKILLed and the unit is 'capped' (its directories stay and
are refused on rerun until discard). Ledger: one start and one finish/capped event per unit (kind 'train', id
train-nN) with the slice's counted flag and per-step exit codes/elapsed seconds.

Interruption and elapsed time (A-1, A-2 of T063): the try block that records an `interrupted` finish event covers the
WHOLE unit: the step loop, the post-condition block (project check, readable test.json) AND the final finish/capped
ledger event. An interrupted unit (any BaseException: KeyboardInterrupt, SIGTERM/SIGHUP via
run_cell.terminate_as_exception) records ONE finish event with outcome 'interrupted' and the elapsed monotonic seconds
since the start event (including a post-check that was running), then re-raises (the running step's process group is
killed by run_cell._spawn_and_wait). That write is WARN-ONLY: a failing ledger prints a warning to stderr and never
replaces the original exception. ledger_sum counts elapsed exactly once because the interrupted event is written only
when the final finish/capped event has not been recorded (flag `recorded`). Residual: a signal that lands between the
return of the final ledger write and the assignment of the flag (one bytecode) could add a second finish event
(over-count, fail-safe); a ledger that fails during the final write itself leads to one attempt to write an
`interrupted` event (warn-only). A normal finish event measures the steps only (not the post-check), as before.
SIGKILL of the driver / power loss leave an orphan child and an incomplete unit: check `ps` for a surviving child
BEFORE --discard (see run_cell docstring (c)).

CLI (from the m1 directory; EXECUTES the project's training, writes under the plan root, user-invoked only; calls
plan_io.mark_started like run_cell, so `python -m ssn_hops.experiments execute` is refused afterwards, F-6):
  python -m driver.train_unit --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice TRAIN-132
  python -m driver.train_unit --plan ... --revision ... --ledger L.jsonl --n 132 [--counted]
Options: --param NAME=VALUE (e.g. train_cap_minutes=90; a name that the slice file does not define as a parameter, and
is not train_cap_minutes, is refused with exit 4; with --n only train_cap_minutes is accepted), --train-cap-minutes M
(positive finite; 0 / negative / nan / inf are refused with exit 4; absent = the parameter / default), --discard,
--keep-going, --env-label X. An unknown --slice id is refused with a message and exit 4. `--n` without `--counted`
prints one stderr line: the minutes are NOT counted in the 360-minute sum (label ADHOC).
Exit codes: 0 ok, 2 failed/invalid post-condition (and any unknown outcome), 3 capped, 4 refused/usage. argparse itself
exits with 2 and a usage text for a non-numeric --train-cap-minutes (not remapped; 2 there means 'bad usage').
There is NO wall option here (S02c-1, D8): training slices keep the per-unit cap.

Bad input instead of a traceback (S02c-1, NB-1): the classes of run_cell.REFUSAL_ERRORS (selector.SelectorError and
plan_io.BindingError, both ValueError subclasses, plus FileNotFoundError and json.JSONDecodeError for a missing or
unparseable file) raised by plan_io.load_for_execution, selector.load_slices and selector.resolve_all print
`refused: <one line>` and exit 4. Any other exception is not caught.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

from ssn_hops import experiment_io as eio
from . import plan_io, run_cell, selector
from .ledger import Ledger, describe_environment, utc_now

EXIT_OK, EXIT_FAILED, EXIT_CAPPED, EXIT_REFUSED = 0, 2, 3, 4
DEFAULT_TRAIN_CAP_MINUTES = 120.0
OK_OUTCOMES = ("ok", "skipped_complete", "supplied_verified")


class TrainRefused(RuntimeError):
    """Unit artifacts exist in an incomplete state (use discard), or the unit does not exist in the plan."""


def model_item(view, n):
    n = str(n)
    if "GLR" not in view.body["policies"]:
        raise TrainRefused("the plan has no GLR policy: no training is planned")
    if n not in view.body["models"]:
        raise TrainRefused(f"N={n} is not a planned model (planned: {sorted(view.body['models'])})")
    return view.body["models"][n]


def evaluation_output(item):
    """The evaluate step's --out path (training/nN/test.json in plans of make_plan)."""
    for step in item["steps"]:
        command = step["command"]
        if step["id"].startswith("evaluate-") and "--out" in command:
            return Path(command[command.index("--out") + 1])
    raise TrainRefused("the plan has no evaluate step with --out")


def step_logs(view, step):
    prefix = str(view.root / "logs" / step["id"])
    return [Path(prefix + suffix) for suffix in run_cell.STATUS_SUFFIXES]


def evaluation_logs(view, item):
    return [p for step in item["steps"] if step["id"].startswith("evaluate-") for p in step_logs(view, step)]


def unit_paths(view, item):
    logs = [p for step in item["steps"] for p in step_logs(view, step)]
    return Path(item["data"]), Path(item["run"]), evaluation_output(item), logs


def project_check(view, n):
    """The project's own check for ONE model: experiments.preflight_models on a plan restricted to N (needs torch).

    preflight_models reads only plan['body']['policies'|'models'|'scenarios'] and handles each model independently,
    so the record equals the one the full-plan call produces for this N. Raises when the run is not complete/loadable.
    """
    from ssn_hops import experiments
    body = dict(view.body)
    body["models"] = {str(n): view.body["models"][str(n)]}
    return experiments.preflight_models({"body": body})[str(n)]


def _readable(path):
    try:
        eio.read(path)
        return True
    except Exception:
        return False


def light_state(view, n):
    """Cheap, torch-free state for status displays: 'complete' | 'absent' | 'partial' (NOT the project's check)."""
    item = model_item(view, n)
    data, run, test, logs = unit_paths(view, item)
    if not any(p.exists() for p in (data, run, test, *logs)):
        return "absent"
    try:
        finished = eio.read(run / "complete.json").get("training_finished") is True
    except Exception:
        finished = False
    return "complete" if finished and (run / "best.pt").exists() and _readable(test) else "partial"


def check_could_not_run(exc):
    """True when a project-check exception says the check could not run (A-4), not that the run is damaged.

    ImportError (torch or another dependency missing) and OSError other than the layout errors FileNotFoundError,
    NotADirectoryError, IsADirectoryError (I/O trouble: PermissionError, EIO, ENOSPC ...).
    """
    if isinstance(exc, ImportError):
        return True
    return isinstance(exc, OSError) and not isinstance(exc, (FileNotFoundError, NotADirectoryError, IsADirectoryError))


def classify(view, n, check):
    """State of the unit, existing paths, error text or None.

    States: 'absent' | 'complete' | 'run_complete_no_evaluation' | 'run_complete_bad_evaluation' (the run passes the
    project check, test.json exists but is not readable JSON; F-5) | 'check_unavailable' (the project check could not
    run: ImportError / I/O OSError, A-4; never deletable) | 'incomplete' (anything else present, including a run that
    fails the project check with a genuine error).
    """
    item = model_item(view, n)
    data, run, test, logs = unit_paths(view, item)
    present = [p for p in (data, run, test, *logs) if p.exists()]
    if not present:
        return "absent", [], None
    if not run.exists():
        return "incomplete", present, "run directory is absent but other artifacts of the unit exist"
    try:
        check(view, n)
    except Exception as exc:
        if check_could_not_run(exc):
            return "check_unavailable", present, f"{type(exc).__name__}: {exc}"
        return "incomplete", present, f"{type(exc).__name__}: {exc}"
    if test.exists():
        if _readable(test):
            return "complete", present, None
        return "run_complete_bad_evaluation", present, "evaluate output exists but is not readable JSON"
    return "run_complete_no_evaluation", present, None


def _inside_root(view, path):
    return Path(path).resolve().is_relative_to(view.root.resolve())


def discard_unit(view, n, only_evaluation=False):
    item = model_item(view, n)
    if item.get("supplied"):
        raise TrainRefused("a supplied model is never discarded")
    data, run, test, logs = unit_paths(view, item)
    targets = [test, *evaluation_logs(view, item)] if only_evaluation else [data, run, test, *logs]
    removed = []
    for path in targets:
        if not _inside_root(view, path):
            raise TrainRefused(f"refusing to delete outside the plan root: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            continue
        removed.append(str(Path(path).resolve().relative_to(view.root.resolve())))
    return removed


def _record_interrupted_unit(ledger, uid, stamp, t0, exc, log, common):
    """Ledger finish event of an interrupted unit; a failing ledger must not mask the original exception (A-1)."""
    try:
        ledger.record("finish", "train", uid, started_utc=stamp, finished_utc=utc_now(),
                      elapsed_s=time.monotonic() - t0, exit_code=None, outcome="interrupted",
                      exception=f"{type(exc).__name__}: {exc}", steps=log, **common)
    except Exception as ledger_exc:
        print(f"warning: the ledger finish event of the interrupted training unit {uid} could not be written: "
              f"{type(ledger_exc).__name__}: {ledger_exc}", file=sys.stderr)


def run_train_unit(view, n, *, ledger, slice_id=None, counted=True, cap_seconds=None, discard=False, check=None):
    """Train (or skip) ONE N. Returns {'outcome': skipped_complete|supplied_verified|ok|failed|capped|invalid_postcondition, ...}."""
    if cap_seconds is not None and not cap_seconds > 0:
        raise ValueError("cap_seconds must be positive")
    if os.name != "posix":
        raise OSError("capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope")
    check = check or project_check
    n = str(n)
    item = model_item(view, n)
    uid = f"train-n{n}"
    common = {"slice_id": slice_id, "counted": counted}
    if item.get("supplied"):
        try:
            check(view, n)
        except Exception as exc:
            ledger.record("refused", "train", uid, reason="supplied_model_check_failed", verify_error=str(exc), **common)
            raise TrainRefused(f"{uid}: the supplied model fails the project's check: {type(exc).__name__}: {exc}") from exc
        ledger.record("skipped", "train", uid, reason="supplied_model_verified", elapsed_s=0.0, **common)
        return {"outcome": "supplied_verified", "id": uid}
    state, present, error = classify(view, n, check)
    root = view.root.resolve()
    names = [str(Path(p).resolve().relative_to(root)) if _inside_root(view, p) else str(p) for p in present]
    if state == "check_unavailable":
        ledger.record("refused", "train", uid, reason="project_check_could_not_run", present=names,
                      verify_error=error, **common)
        raise TrainRefused(f"{uid}: the project's completeness check could not run ({error}); this says nothing about "
                           f"the state of the run, so nothing is deleted, even with discard. Fix the environment "
                           f"(is torch installed? is the file system readable?) and run again ({names})")
    if state == "complete":
        ledger.record("skipped", "train", uid, reason="verified_complete", elapsed_s=0.0, **common)
        return {"outcome": "skipped_complete", "id": uid}
    steps = list(item["steps"])
    if state == "incomplete":
        if not discard:
            ledger.record("refused", "train", uid, reason="incomplete_training_directory", present=names,
                          verify_error=error, **common)
            raise TrainRefused(f"{uid}: incomplete training artifacts exist ({names}); train() has no resume and "
                               f"generate refuses an existing directory; not touching them without discard "
                               f"(check said: {error})")
        ledger.record("discarded", "train", uid, removed=discard_unit(view, n), verify_error=error, **common)
    elif state in ("run_complete_no_evaluation", "run_complete_bad_evaluation"):
        bad_evaluation = state == "run_complete_bad_evaluation"
        leftovers = [p for p in (evaluation_output(item), *evaluation_logs(view, item)) if p.exists()]
        if leftovers and not discard:
            ledger.record("refused", "train", uid,
                          reason="unreadable_evaluation_output" if bad_evaluation else "incomplete_evaluation_logs",
                          present=names, verify_error=error, **common)
            raise TrainRefused(f"{uid}: the run passes the project check but evaluate artifacts of an earlier attempt "
                               f"exist (test.json and/or evaluate logs; check said: {error}); pass discard to remove "
                               f"ONLY the evaluation artifacts and rerun evaluate (the training is kept)")
        if leftovers:
            ledger.record("discarded", "train", uid, removed=discard_unit(view, n, only_evaluation=True),
                          scope="evaluation_only", **common)
        steps = [s for s in steps if s["id"].startswith("evaluate-")]
    stamp = utc_now()
    ledger.record("start", "train", uid, started_utc=stamp, cap_seconds=cap_seconds,
                  steps=[s["id"] for s in steps], **common)
    t0 = time.monotonic()
    log, outcome, exit_code = [], "ok", 0
    recorded = False
    try:
        for step in steps:
            remaining = None if cap_seconds is None else cap_seconds - (time.monotonic() - t0)
            if remaining is not None and remaining <= 0:
                outcome, exit_code = "capped", None
                break
            record, capped, elapsed = run_cell._spawn_and_wait(view, step, remaining)
            log.append({"id": step["id"], "exit_code": record["exit_code"], "elapsed_s": elapsed, "capped": capped})
            exit_code = record["exit_code"]
            if capped:
                outcome = "capped"
                break
            if exit_code != 0:
                outcome = "failed"
                break
        elapsed_total = time.monotonic() - t0
        verified, verify_error = None, None
        if outcome == "ok":
            try:
                check(view, n)
                if not _readable(evaluation_output(item)):
                    raise ValueError("evaluate output is missing or not readable JSON")
                verified = True
            except Exception as exc:
                outcome, verified, verify_error = "invalid_postcondition", False, f"{type(exc).__name__}: {exc}"
        ledger.record("capped" if outcome == "capped" else "finish", "train", uid, started_utc=stamp,
                      finished_utc=utc_now(), elapsed_s=elapsed_total, exit_code=exit_code, outcome=outcome,
                      verified=verified, verify_error=verify_error, steps=log, cap_seconds=cap_seconds, **common)
        recorded = True
    except BaseException as exc:
        if not recorded:
            _record_interrupted_unit(ledger, uid, stamp, t0, exc, log, common)
        raise
    return {"outcome": outcome, "id": uid, "elapsed_s": elapsed_total, "exit_code": exit_code,
            "steps": log, "verified": verified}


def exit_code_of(result):
    """Process exit code of one unit result; an unknown outcome is never green (A-7)."""
    outcome = result["outcome"]
    if outcome == "capped":
        return EXIT_CAPPED
    if outcome in OK_OUTCOMES:
        return EXIT_OK
    return EXIT_FAILED


def main(argv=None):
    parser = argparse.ArgumentParser(description="run the training unit of one N (user-invoked; executes training)")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--plan-sha256")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slice", dest="slice_id")
    group.add_argument("--n")
    parser.add_argument("--slices", default=str(Path(__file__).resolve().parents[1] / "slices.json"))
    parser.add_argument("--param", action="append", help="override a slices.json parameter, NAME=VALUE")
    parser.add_argument("--train-cap-minutes", type=float)
    parser.add_argument("--counted", action="store_true", help="--n mode: count in the SUM")
    parser.add_argument("--discard", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--env-label")
    args = parser.parse_args(argv)
    problem = run_cell.check_cap_minutes(train_cap_minutes=args.train_cap_minutes)
    if problem:
        print(f"refused: {problem}")
        return EXIT_REFUSED
    try:
        overrides = run_cell._params(args.param)
    except ValueError as exc:
        print(f"refused: {exc}")
        return EXIT_REFUSED
    if args.n is not None:
        unknown = sorted(set(overrides) - {"train_cap_minutes"})
        if unknown:
            print(f"refused: --param name(s) {unknown} have no effect with --n (only train_cap_minutes is read)")
            return EXIT_REFUSED
    if args.n is not None and not args.counted:
        print("note: --n without --counted: the minutes of this run are NOT counted in the 360-minute sum "
              "(label ADHOC, counted false); add --counted to count them", file=sys.stderr)
    try:
        view = plan_io.load_for_execution(args.plan, args.revision, expected_plan_sha256=args.plan_sha256)
    except run_cell.REFUSAL_ERRORS as exc:
        return run_cell.refuse_with(exc)
    plan_io.mark_started(view)
    ledger = Ledger(args.ledger, plan_sha256=view.sha256, revision=view.revision, source_sha256=view.source_hash,
                    environment=describe_environment(args.env_label))
    if args.slice_id:
        try:
            spec = selector.load_slices(args.slices)
        except run_cell.REFUSAL_ERRORS as exc:
            return run_cell.refuse_with(exc)
        unknown = run_cell.unknown_params(overrides, spec)
        if unknown:
            print(f"refused: --param name(s) {unknown} are not defined as parameters in {args.slices} "
                  f"(defined: {sorted(spec.get('parameters', {}))}; train_cap_minutes is always accepted)")
            return EXIT_REFUSED
        params = {**spec.get("parameters", {}), **overrides}
        spec["parameters"] = params
        try:
            resolved_all = selector.resolve_all(view, spec)
        except run_cell.REFUSAL_ERRORS as exc:
            return run_cell.refuse_with(exc)
        if args.slice_id not in resolved_all:
            print(f"refused: unknown slice {args.slice_id!r} in {args.slices} (known: {list(resolved_all)})")
            return EXIT_REFUSED
        resolved = resolved_all[args.slice_id]
        label, counted, ns = args.slice_id, resolved["counted"], list(resolved["train_ns"])
        if not ns:
            print(f"refused: slice {args.slice_id} has no train step")
            return EXIT_REFUSED
    else:
        params = overrides
        label, counted, ns = "ADHOC", args.counted, [args.n]
    if args.train_cap_minutes is not None:
        minutes = args.train_cap_minutes
    else:
        minutes = params.get("train_cap_minutes", DEFAULT_TRAIN_CAP_MINUTES)
    code = EXIT_OK
    with run_cell.terminate_as_exception():
        try:
            for n in ns:
                result = run_train_unit(view, n, ledger=ledger, slice_id=label, counted=counted,
                                        cap_seconds=minutes * 60, discard=args.discard)
                print(json.dumps(result, sort_keys=True))
                bad = exit_code_of(result)
                code = max(code, bad)
                if bad and not args.keep_going:
                    break
        except TrainRefused as exc:
            print(f"refused: {exc}")
            return EXIT_REFUSED
    return code


if __name__ == "__main__":
    sys.exit(main())
