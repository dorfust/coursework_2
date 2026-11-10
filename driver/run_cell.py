"""Capped single-cell runner: ONE cell exactly like experiment_io.job() (blob 0119dfc5). Written, NOT run.

Mirrors job(): logs/<id>.started.json, .stdout.txt, .stderr.txt (exclusive create), argv =
[sys.executable, *command[1:]], status record {id, argv, cwd, revision, plan_sha256, exit_code, exception,
log_sha256{.stdout.txt,.stderr.txt}} written with experiment_io.write to logs/<id>.status.json. Differences:
(a) subprocess.Popen in a NEW SESSION (start_new_session=True -> setsid, so the child is leader of a new
process group whose id is its pid) and, on cap expiry, os.killpg(pid, SIGKILL): signals every member of the
group, cannot be ignored, and the group id is valid because the leader is not yet reaped when wait(timeout)
expires. A descendant that itself calls setsid escapes (not handled). POSIX only (Linux, WSL2).
(b) a capped cell gets the normal status record with exit_code = the kill returncode (negative signal
number), exception = 'CellCapExceeded: ...' and extra keys capped/cap_seconds; the aggregator's
_verify_cell treats exit_code != 0 or exception != None as not successful and returns None (missing/failed).
This driver NEVER writes complete.json (only the child can).
(c) Interruption. Any BaseException raised while the child runs (KeyboardInterrupt, or SIGTERM / SIGHUP turned into
TerminationSignal, a SystemExit subclass with code 128 + signal number, by terminate_as_exception()) kills the
child's whole process group and writes a status record (exit_code None, exception text); run_cell() then records a
ledger `finish` event with outcome `interrupted` (elapsed monotonic seconds, exception text, counted flag) and
re-raises. terminate_as_exception() is installed ONLY by the CLI main() functions (never at import, main thread
only, previous handlers restored on exit); library callers who want the same behaviour use the context manager.
A signal that is IGNORED when the block starts (for example SIGHUP under `nohup`) stays ignored: such a driver does
not react to it, and its child keeps running (use SIGTERM or SIGINT to stop it cleanly).
A-3 (T063): after the FIRST termination signal has been turned into the exception, the handler sets the same
signals to SIG_IGN before it raises, so a SECOND SIGTERM/SIGHUP during the cleanup (killpg, status write, ledger
event) cannot abort the cleanup; the saved handlers are restored when the block ends. Remaining window (milliseconds):
a signal that lands BEFORE the child's Popen object is bound to `proc` (inside Popen between fork and return, or
between its return and the assignment) is raised while `proc` is still None, so the child is NOT killed and runs
on as an orphan in its own session (status record written, cell 'incomplete'): check `ps` before --discard. KeyboardInterrupt
(SIGINT) is not covered by the SIG_IGN step (a second Ctrl-C can still interrupt the cleanup).
NOT covered: SIGKILL of the driver, power loss, an OOM kill or a hard crash. Then the child (own session) is NOT
killed and runs on as an ORPHAN, logs/<id>.started.json exists without status.json, and the cell is 'incomplete'
(the next run refuses it). BEFORE `--discard` on such a cell check `ps` for a surviving child (for example
`ps -eo pid,pgid,etime,args | grep ssn_hops`), kill its process group or wait for it; --discard deletes runs/<id>
and logs/<id>.* and a still running child would keep writing into a deleted or re-created directory.
(d) Outcomes: ok (child exit 0, valid complete.json, verifier returned a record = verified True), unverified (child
exit 0 and valid complete.json, but the verifier returned None or raised: verified False, verify_error set; exit
code 2, never 0), ok_unverified_by_request (verify_after=False, library use only: verified None; exit code 0
because the caller asked not to verify; the CLI never passes verify_after=False), failed, invalid_completion,
capped, skipped_verified, wall_reached (S02c-1, see the wall option below: the cell was NOT started; exit code 3);
an interrupted cell raises instead of returning.
Resume: a cell whose verifier returns a record is skipped; a cell with ANY leftover artifact that does not
verify (including an `unverified` one) is refused unless discard=True (deletes runs/<id> and logs/<id>.* and records
'discarded'). Single worker; the child environment is inherited unchanged.

T058-S02 integration: a slice's train steps are delegated to driver.train_unit.run_train_unit (cap = slices.json
parameter train_cap_minutes, default 120, override --param train_cap_minutes=NN or --train-cap-minutes); the
'refused: train step is W1b' branch is gone. The training unit reuses _spawn_and_wait of this module.

CLI (from the m1 directory; EXECUTES simulations/training, writes under the plan root, user-invoked only):
  python -m driver.run_cell --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice PILOT
  python -m driver.run_cell --plan ... --revision ... --ledger L.jsonl --cell <cell-id> [--counted] [--cap-minutes M]
  python -m driver.run_cell --plan ... --revision ... --ledger L.jsonl --slice B1B --cells-only --cap-minutes C --wall-minutes W
Options: --cells-only (skip train steps), --keep-going, --discard, --param NAME=VALUE, --train-cap-minutes M,
--env-label X, --wall-minutes W. Cap options (and --wall-minutes) must be positive finite numbers of minutes (0,
negative, nan, inf are refused with exit 4; absence of the option = no cap / no wall).
Exit codes: 0 ok, 2 failed/invalid completion/unverified, 3 capped OR wall reached (the slice is NOT finished),
4 refused/usage.
Input checks (T063, A-5/A-6): an unknown --slice id is refused with a message and exit 4; a --param name that the
slice file does not define as a parameter (train_cap_minutes is always accepted) is refused with exit 4, and --param
is refused with --cell (it would have no effect); `--cell` WITHOUT `--counted` prints one stderr line that the
minutes are NOT counted in the 360-minute sum (label ADHOC, counted false) and that --counted counts them (no change
of the default). argparse itself exits with 2 and a usage text for a non-numeric cap option (not remapped; 2 there
means 'bad usage', not 'cell failed').

Wall option (S02c-1, decision D8): --wall-minutes W lets a cells slice stop BY ITSELF when the wall budget W is
used up, so that a controller need not kill the driver. Rules (each violation is `refused: ...`, exit 4, checked
BEFORE the plan is loaded): it needs --cap-minutes (without a cap a cell could run past the wall), it needs
--cells-only (a training step has no wall in this option; run slices with train steps with --cells-only), and it is
refused with --cell (a single cell has no wall). The clock (time.monotonic) starts right after those argument
checks and BEFORE load_for_execution and ensure_traces, so trace generation counts against the wall. Inside
run_cell(..., deadline=<monotonic value>) the check sits AFTER the 'verified -> skipped' branch and BEFORE the
'incomplete' handling and the ledger start: if the remaining wall is LESS than cap_seconds the cell is not started and
the result is {'outcome': 'wall_reached', 'id', 'remaining_s', 'cap_seconds'}: no ledger event, nothing discarded or
touched (an incomplete cell stays as it is, also with discard=True). So a verified cell is skipped for free at any
time, and a cell starts only when its full cap still fits. wall_reached is printed like any result line, has exit
code 3 and stops the loop even with --keep-going (every later cell would meet the same wall). A deadline without
cap_seconds is a ValueError. Remaining overshoot: the time that one started cell needs after a start that fitted
(at most its cap) plus the ledger write; the clock is not shared with train steps (none run with this option).

Bad input instead of a traceback (S02c-1, NB-1): SelectorError (driver/selector.py, a ValueError), BindingError
(driver/plan_io.py, a ValueError) and, for a missing or unparseable file, FileNotFoundError and
json.JSONDecodeError raised by plan_io.load_for_execution, selector.load_slices and selector.resolve_all print
`refused: <one line>` and exit 4 (REFUSAL_ERRORS). Not caught: any other exception, for example the AttributeError
of a slice file that is valid JSON but not an object.
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from ssn_hops import experiment_io as eio
from . import plan_io, selector, traces
from .ledger import Ledger, describe_environment, utc_now

STATUS_SUFFIXES = (".started.json", ".stdout.txt", ".stderr.txt", ".status.json")
EXIT_OK, EXIT_FAILED, EXIT_CAPPED, EXIT_REFUSED = 0, 2, 3, 4
DEFAULT_TRAIN_CAP_MINUTES = 120.0
# NB-1: the classes that a bad slice file, a bad plan binding or a missing / unparseable file raise in the mains.
REFUSAL_ERRORS = (selector.SelectorError, plan_io.BindingError, FileNotFoundError, json.JSONDecodeError)


class CellRefused(RuntimeError):
    """A cell directory/log set exists in an incomplete or inconsistent state (use discard)."""


class TerminationSignal(SystemExit):
    """SIGTERM / SIGHUP received while the driver runs inside terminate_as_exception(); exit code 128 + signal."""

    def __init__(self, signum):
        super().__init__(128 + int(signum))
        self.signum = int(signum)

    def __str__(self):
        try:
            name = signal.Signals(self.signum).name
        except ValueError:
            name = str(self.signum)
        return f"driver received {name}"


@contextlib.contextmanager
def terminate_as_exception(signals=None):
    """Turn SIGTERM and SIGHUP into TerminationSignal for the duration of the block (yields True in the main thread).

    Only in the main thread (elsewhere nothing is installed and False is yielded: signal.signal would raise); the
    previous handlers are restored on exit; never called at import time. A signal that is ignored (SIG_IGN) when the
    block starts, for example SIGHUP under `nohup`, is left ignored. The raised exception passes through the
    existing BaseException path of _spawn_and_wait, which kills the child's process group and writes the status record.

    A-3: the handler first sets every signal that THIS call installed to SIG_IGN and then raises, so a second
    termination signal during the cleanup is ignored instead of aborting it; the saved handlers are put back in the
    `finally` (also after the first signal). Remaining window, milliseconds wide: a signal that arrives before the
    child's Popen object is bound to `proc` in _spawn_and_wait is raised with proc still None, the child is then not
    killed (orphan in its own session, status record written); see the module docstring (c).
    """
    if signals is None:
        signals = [getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]
    if threading.current_thread() is not threading.main_thread():
        yield False
        return

    previous = {}

    def handler(signum, frame):
        for installed in list(previous):
            signal.signal(installed, signal.SIG_IGN)
        raise TerminationSignal(signum)

    try:
        for signum in signals:
            if signal.getsignal(signum) == signal.SIG_IGN:
                continue
            previous[signum] = signal.signal(signum, handler)
        yield True
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old if old is not None else signal.SIG_DFL)


def check_cap_minutes(**named):
    """Error text for the first cap option that is given but not a positive finite number, else None."""
    for name, value in named.items():
        if value is not None and not 0 < value < math.inf:
            return (f"--{name.replace('_', '-')} must be a positive finite number of minutes (got {value}); "
                    f"omit the option for no cap")
    return None


def exit_code_of(result):
    """Process exit code of one run_cell result; an unknown outcome is never green.

    3 = capped or wall reached: the slice is NOT finished.
    """
    outcome = result["outcome"]
    if outcome in ("capped", "wall_reached"):
        return EXIT_CAPPED
    if outcome in ("ok", "skipped_verified", "ok_unverified_by_request"):
        return EXIT_OK
    return EXIT_FAILED


def one_line(exc):
    """str(exc) with every run of whitespace collapsed to one space (a refusal is ONE line)."""
    return " ".join(str(exc).split())


def refuse_with(exc):
    """NB-1: print `refused: <one line>` for a REFUSAL_ERRORS exception and return the exit code 4."""
    print(f"refused: {one_line(exc)}")
    return EXIT_REFUSED


def _glr_records(view, cell, scenario):
    """model_records for a GLR cell: model_preflight.json when it exists (full check), else resume mode.

    Resume mode (no model_preflight.json yet, `finish preflight` writes it): the identity expected by _verify_cell is built
    from the cell's own result.json checkpoint block, after requiring that the planned run's best.pt hashes
    to that checkpoint sha256. The aggregator's verify_models re-checks everything later.
    """
    preflight = view.root / "model_preflight.json"
    if preflight.exists():
        record = eio.read(preflight)
        if record["plan_sha256"] != view.sha256:
            raise ValueError("model_preflight.json belongs to another plan")
        return record["models"]
    out = eio.inside(view.root, cell["out"])
    ckpt = eio.read(out / "result.json")["timing"]["checkpoint"]
    n = str(scenario["config"]["orbit"]["n"])
    best = Path(view.body["models"][n]["run"]) / "best.pt"
    if not best.exists() or eio.digest(best) != ckpt["sha256"]:
        raise ValueError("GLR checkpoint of the cell differs from the planned model best.pt")
    return {n: {"checkpoint_sha256": ckpt["sha256"], "training_config_sha256": ckpt["training_config_sha256"],
                "training_revision": ckpt["training_revision"], "epoch": ckpt["epoch"],
                "feature_spec": ckpt["feature_spec"]}}


def resume_verifier(view, cell):
    """The aggregator's own per-cell verification (experiment_results.verify_cell -> _verify_cell).

    Returns the verified record, or None (missing / failed / capped); raises ValueError on inconsistency.
    """
    from ssn_hops import experiment_results as results
    scenario = view.scenario_of(cell)
    records = _glr_records(view, cell, scenario) if cell["policy"] == "GLR" else {}
    return results.verify_cell(view.plan, cell, scenario, records)


def cell_paths(view, cell):
    out = eio.inside(view.root, cell["out"])
    prefix = view.root / "logs" / cell["id"]
    return out, [Path(str(prefix) + suffix) for suffix in STATUS_SUFFIXES]


def classify(view, cell, verifier):
    """('absent' | 'verified' | 'incomplete', existing paths, error text or None)."""
    out, logs = cell_paths(view, cell)
    present = [p for p in (out, *logs) if p.exists()]
    if not present:
        return "absent", [], None
    try:
        value, error = verifier(view, cell), None
    except Exception as exc:
        value, error = None, f"{type(exc).__name__}: {exc}"
    return ("verified" if value is not None else "incomplete"), present, error


def discard_cell(view, cell):
    out, logs = cell_paths(view, cell)
    removed = []
    for path in (out, *logs):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            continue
        removed.append(str(path.relative_to(view.root.resolve())) if path.is_relative_to(view.root.resolve()) else str(path))
    return removed


def kill_tree(proc):
    """SIGKILL the child's whole process group (the child is its leader); returns its returncode."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return proc.wait()


def _spawn_and_wait(view, cell, cap_seconds):
    """job() mirror with a cap. ``cell`` needs only 'id' and 'command' (also used for training steps).

    Returns (record, capped, elapsed_s).
    """
    logs = view.root / "logs"
    logs.mkdir(exist_ok=True)
    prefix = logs / cell["id"]
    argv = [sys.executable, *cell["command"][1:]]
    record = {"id": cell["id"], "argv": argv, "cwd": str(Path.cwd()),
              "revision": view.revision, "plan_sha256": view.sha256}
    eio.write(str(prefix) + ".started.json", record)
    capped, proc, elapsed = False, None, None
    try:
        with Path(str(prefix) + ".stdout.txt").open("x", encoding="utf-8") as stdout:
            with Path(str(prefix) + ".stderr.txt").open("x", encoding="utf-8") as stderr:
                t0 = time.monotonic()
                proc = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    returncode = proc.wait(timeout=cap_seconds)
                except subprocess.TimeoutExpired:
                    capped = True
                    returncode = kill_tree(proc)
                elapsed = time.monotonic() - t0
        record.update({"exit_code": returncode, "exception": None})
        if capped:
            record.update({"exception": f"CellCapExceeded: killed after {cap_seconds} s wall clock",
                           "capped": True, "cap_seconds": cap_seconds})
    except BaseException as exc:
        if proc is not None and proc.poll() is None:
            kill_tree(proc)
        record.update({"exit_code": None, "exception": f"{type(exc).__name__}: {exc}"})
        eio.write(str(prefix) + ".status.json", record)
        raise
    record["log_sha256"] = {suffix: eio.digest(str(prefix) + suffix) for suffix in (".stdout.txt", ".stderr.txt")}
    eio.write(str(prefix) + ".status.json", record)
    return record, capped, elapsed


def _judge(view, cell, record, verifier, verify_after):
    """(outcome, verified, verify_error) of a child that was not capped."""
    if record["exit_code"] != 0:
        return "failed", None, None
    output = eio.inside(view.root, cell["out"])
    try:
        complete = eio.read(output / "complete.json")
        valid = (complete.get("simulation_finished") is True
                 and complete["result_sha256"] == eio.digest(output / "result.json"))
    except Exception:
        valid = False
    if not valid:
        return "invalid_completion", None, None   # execute_suite raises here: 'child exited zero without a valid completion record'
    if not verify_after:
        return "ok_unverified_by_request", None, None
    try:
        verified = verifier(view, cell) is not None
        verify_error = None if verified else "the verifier returned None: the cell is missing, failed or not successful"
    except Exception as exc:
        verified, verify_error = False, f"{type(exc).__name__}: {exc}"
    return ("ok" if verified else "unverified"), verified, verify_error


def _record_interrupted(ledger, cell_id, stamp, t0, exc, common):
    """Ledger finish event of an interrupted cell; a failing ledger must not mask the original exception."""
    try:
        ledger.record("finish", "cell", cell_id, started_utc=stamp, finished_utc=utc_now(),
                      elapsed_s=time.monotonic() - t0, exit_code=None, outcome="interrupted",
                      exception=f"{type(exc).__name__}: {exc}", **common)
    except Exception as ledger_exc:
        print(f"warning: the ledger finish event of the interrupted cell {cell_id} could not be written: "
              f"{type(ledger_exc).__name__}: {ledger_exc}", file=sys.stderr)


def run_cell(view, cell_id, *, ledger, slice_id=None, counted=True, cap_seconds=None, discard=False,
             verifier=None, verify_after=True, deadline=None):
    """Run (or skip) ONE cell.

    Returns {'outcome': skipped_verified|ok|unverified|ok_unverified_by_request|failed|invalid_completion|capped|
    wall_reached, ...}; raises (after recording a ledger finish event with outcome 'interrupted') when interrupted.

    deadline (S02c-1, D8): a time.monotonic() value or None. With a deadline, cap_seconds is required (ValueError
    otherwise). After the 'verified -> skipped' branch and BEFORE the incomplete handling and the ledger start: when
    deadline - time.monotonic() < cap_seconds the cell is not started and {'outcome': 'wall_reached', 'id',
    'remaining_s', 'cap_seconds'} is returned: no ledger event, nothing touched or discarded (also with discard=True).
    """
    if cap_seconds is not None and not cap_seconds > 0:
        raise ValueError("cap_seconds must be positive")
    if deadline is not None and cap_seconds is None:
        raise ValueError("a deadline needs cap_seconds (a cell without a cap could run past the wall)")
    if os.name != "posix":
        raise OSError("capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope")
    verifier = verifier or resume_verifier
    cell = view.cell(cell_id)
    common = {"slice_id": slice_id, "counted": counted}
    state, present, error = classify(view, cell, verifier)
    if state == "verified":
        ledger.record("skipped", "cell", cell_id, reason="verified_complete", elapsed_s=0.0, **common)
        return {"outcome": "skipped_verified", "id": cell_id}
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining < cap_seconds:
            return {"outcome": "wall_reached", "id": cell_id, "remaining_s": remaining, "cap_seconds": cap_seconds}
    if state == "incomplete":
        names = [str(p.relative_to(view.root.resolve())) for p in present]
        if not discard:
            ledger.record("refused", "cell", cell_id, reason="incomplete_cell_directory", present=names,
                          verify_error=error, **common)
            raise CellRefused(f"{cell_id}: incomplete cell artifacts exist ({names}); not touching them "
                              f"without discard (verification said: {error})")
        ledger.record("discarded", "cell", cell_id, removed=discard_cell(view, cell), verify_error=error, **common)
    stamp = utc_now()
    ledger.record("start", "cell", cell_id, started_utc=stamp, cap_seconds=cap_seconds, **common)
    t0 = time.monotonic()
    try:
        record, capped, elapsed = _spawn_and_wait(view, cell, cap_seconds)
        outcome, verified, verify_error = (None, None, None) if capped else _judge(
            view, cell, record, verifier, verify_after)
    except BaseException as exc:
        _record_interrupted(ledger, cell_id, stamp, t0, exc, common)
        raise
    if capped:
        ledger.record("capped", "cell", cell_id, started_utc=stamp, finished_utc=utc_now(), elapsed_s=elapsed,
                      exit_code=record["exit_code"], cap_seconds=cap_seconds, outcome="capped", **common)
        return {"outcome": "capped", "id": cell_id, "elapsed_s": elapsed, "exit_code": record["exit_code"]}
    ledger.record("finish", "cell", cell_id, started_utc=stamp, finished_utc=utc_now(), elapsed_s=elapsed,
                  exit_code=record["exit_code"], outcome=outcome, verified=verified, verify_error=verify_error,
                  **common)
    return {"outcome": outcome, "id": cell_id, "elapsed_s": elapsed, "exit_code": record["exit_code"],
            "verified": verified, "verify_error": verify_error}


def _params(pairs):
    """NAME=VALUE overrides as floats; a malformed or non-positive/non-finite value raises ValueError."""
    out = {}
    for pair in pairs or []:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise ValueError(f"--param needs NAME=VALUE, got {pair!r}")
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"--param {name}: {value!r} is not a number") from None
        if not 0 < number < math.inf:
            raise ValueError(f"--param {name}={value}: must be a positive finite number")
        out[name] = number
    return out


def unknown_params(overrides, spec):
    """Sorted --param names that the slice file does not define as parameters (train_cap_minutes is always accepted)."""
    return sorted(set(overrides) - set(spec.get("parameters", {})) - {"train_cap_minutes"})


def wall_option_problem(args):
    """Refusal text of a bad --wall-minutes combination (S02c-1, W-2), else None. Checked before the plan is loaded."""
    if args.wall_minutes is None:
        return None
    if args.cell:
        return "--wall-minutes has no effect with --cell (a single cell has no wall); use it with --slice"
    if args.cap_minutes is None:
        return "--wall-minutes requires --cap-minutes (a cell without a cap could run past the wall)"
    if not args.cells_only:
        return ("--wall-minutes requires --cells-only (a training step has no wall in this option; run slices "
                "that contain train steps with --cells-only)")
    return None


def main(argv=None):
    from . import train_unit      # lazy: train_unit imports this module
    parser = argparse.ArgumentParser(description="run capped M1 cells sequentially (user-invoked; executes simulations)")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--plan-sha256")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slice", dest="slice_id")
    group.add_argument("--cell")
    parser.add_argument("--slices", default=str(Path(__file__).resolve().parents[1] / "slices.json"))
    parser.add_argument("--param", action="append", help="override a slices.json parameter, NAME=VALUE")
    parser.add_argument("--cap-minutes", type=float)
    parser.add_argument("--train-cap-minutes", type=float)
    parser.add_argument("--wall-minutes", type=float,
                        help="stop by itself when fewer than --cap-minutes remain of this wall (needs --cap-minutes, "
                             "--cells-only; not with --cell)")
    parser.add_argument("--counted", action="store_true", help="single-cell mode: count in the SUM")
    parser.add_argument("--cells-only", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--discard", action="store_true")
    parser.add_argument("--env-label")
    args = parser.parse_args(argv)
    problem = check_cap_minutes(cap_minutes=args.cap_minutes, train_cap_minutes=args.train_cap_minutes,
                                wall_minutes=args.wall_minutes)
    if problem:
        print(f"refused: {problem}")
        return EXIT_REFUSED
    try:
        overrides = _params(args.param)
    except ValueError as exc:
        print(f"refused: {exc}")
        return EXIT_REFUSED
    if args.cell and overrides:
        print(f"refused: --param {sorted(overrides)} has no effect with --cell (it only overrides slice parameters)")
        return EXIT_REFUSED
    problem = wall_option_problem(args)
    if problem:
        print(f"refused: {problem}")
        return EXIT_REFUSED
    if args.cell and not args.counted:
        print("note: --cell without --counted: the minutes of this run are NOT counted in the 360-minute sum "
              "(label ADHOC, counted false); add --counted to the command to count them", file=sys.stderr)
    wall_t0 = time.monotonic()      # W-3: the wall starts here, before the plan is loaded and the traces are made
    deadline = None if args.wall_minutes is None else wall_t0 + args.wall_minutes * 60
    try:
        view = plan_io.load_for_execution(args.plan, args.revision, expected_plan_sha256=args.plan_sha256)
    except REFUSAL_ERRORS as exc:
        return refuse_with(exc)
    plan_io.mark_started(view)
    ledger = Ledger(args.ledger, plan_sha256=view.sha256, revision=view.revision, source_sha256=view.source_hash,
                    environment=describe_environment(args.env_label))
    train_minutes = DEFAULT_TRAIN_CAP_MINUTES
    cell_cap = args.cap_minutes * 60 if args.cap_minutes is not None else None
    if args.cell:
        steps = [{"kind": "cell", "id": args.cell, "trace_path": view.scenario_of(view.cell(args.cell))["trace_path"],
                  "cap_seconds": cell_cap}]
        label, counted, trace_paths = "ADHOC", args.counted, [steps[0]["trace_path"]]
    else:
        try:
            spec = selector.load_slices(args.slices)
        except REFUSAL_ERRORS as exc:
            return refuse_with(exc)
        unknown = unknown_params(overrides, spec)
        if unknown:
            print(f"refused: --param name(s) {unknown} are not defined as parameters in {args.slices} "
                  f"(defined: {sorted(spec.get('parameters', {}))}; train_cap_minutes is always accepted)")
            return EXIT_REFUSED
        spec["parameters"] = {**spec.get("parameters", {}), **overrides}
        train_minutes = spec["parameters"].get("train_cap_minutes", DEFAULT_TRAIN_CAP_MINUTES)
        try:
            resolved_all = selector.resolve_all(view, spec)
        except REFUSAL_ERRORS as exc:
            return refuse_with(exc)
        if args.slice_id not in resolved_all:
            print(f"refused: unknown slice {args.slice_id!r} in {args.slices} (known: {list(resolved_all)})")
            return EXIT_REFUSED
        resolved = resolved_all[args.slice_id]
        steps, label, counted, trace_paths = resolved["steps"], args.slice_id, resolved["counted"], resolved["trace_paths"]
    if args.train_cap_minutes is not None:
        train_minutes = args.train_cap_minutes
    wall_kwargs = {} if deadline is None else {"deadline": deadline}
    code = EXIT_OK
    with terminate_as_exception():
        try:
            traces.ensure_traces(view, trace_paths, ledger=ledger, slice_id=label, counted=counted, discard=args.discard)
            for step in steps:
                if step["kind"] == "train":
                    if args.cells_only:
                        continue
                    result = train_unit.run_train_unit(view, step["n"], ledger=ledger, slice_id=label, counted=counted,
                                                       cap_seconds=train_minutes * 60, discard=args.discard)
                    print(json.dumps(result, sort_keys=True))
                    bad = train_unit.exit_code_of(result)
                    code = max(code, bad)
                    if bad and not args.keep_going:
                        break
                    continue
                if step["kind"] != "cell":
                    continue
                cap = cell_cap if cell_cap is not None else step.get("cap_seconds")
                result = run_cell(view, step["id"], ledger=ledger, slice_id=label, counted=counted,
                                  cap_seconds=cap, discard=args.discard, **wall_kwargs)
                print(json.dumps(result, sort_keys=True))
                bad = exit_code_of(result)
                code = max(code, bad)
                if bad and (not args.keep_going or result["outcome"] == "wall_reached"):
                    break
        except (CellRefused, traces.TraceError, train_unit.TrainRefused) as exc:
            print(f"refused: {exc}")
            return EXIT_REFUSED
    return code


if __name__ == "__main__":
    sys.exit(main())
