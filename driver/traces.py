"""Trace production for a slice: what execute_suite does in-process, resumable. Written, NOT run.

Mirror of experiments.execute_suite (blob 72b6fa02): for each distinct scenario['trace_path'], taken from
the FIRST scenario of the plan that carries it (as execute_suite's ``seen`` set does),
``write(inside(root, trace_path), trace_document(make_trace(cfg), cfg))`` with cfg = from_sim_dict(scenario['config']).
The plan's offline step 'trace-<scenario>' (command ``simulate trace``) is NOT used: execute_suite does not
run it. Resume: an existing trace file is accepted only if it equals the regenerated document; otherwise
refuse (or delete + rewrite with discard=True). Writes go to a temp name and are hard-linked into place, so
an interrupted write never leaves a partial file under the final name and an existing file is never replaced.

Interruption (T063 A-2): if KeyboardInterrupt or SystemExit (SIGTERM/SIGHUP via run_cell.terminate_as_exception)
arrives after the `start` event while a trace is generated, written or linked, or while the final `finish` event is
written, ONE ledger `finish` event with outcome 'interrupted' and the elapsed seconds is recorded (warn-only: a
failing ledger prints a warning to stderr and never replaces the original exception) and the exception is re-raised.
It is not written when the final finish event was already recorded (elapsed counted once). Other exceptions are not
recorded as events (unchanged).

File system problems (T065-A01-S02): in the CLI `main`, an OSError from ensure_traces (no hard links on the work
directory file system, a stale temp file `<name>.tmp<pid>`, a write error) prints ONE line `refused: OSError: ...` and
exits 4 instead of a traceback. ensure_traces itself still raises it (callers such as driver.run_cell are unchanged),
and no ledger `finish` event is written for it (only the `start` event exists).

CLI (from the m1 directory):
  python -m driver.traces --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice ID
"""
import argparse
import os
import sys
import time

from ssn_hops import experiment_io as eio
from .ledger import utc_now


class TraceError(RuntimeError):
    """An existing trace file does not match the regenerated trace."""


def default_make(config):
    from ssn_hops.sim_config import from_sim_dict
    from ssn_hops.traffic import make_trace, trace_document
    cfg = from_sim_dict(config)
    return trace_document(make_trace(cfg), cfg)


def _record_interrupted_trace(ledger, item_id, slice_id, counted, stamp, t0, exc):
    """Warn-only `interrupted` finish event of a trace being written."""
    try:
        ledger.record("finish", "trace", item_id, slice_id=slice_id, counted=counted, started_utc=stamp,
                      finished_utc=utc_now(), elapsed_s=time.monotonic() - t0, exit_code=None,
                      outcome="interrupted", exception=f"{type(exc).__name__}: {exc}")
    except Exception as ledger_exc:
        print(f"warning: the ledger finish event of the interrupted trace {item_id} could not be written: "
              f"{type(ledger_exc).__name__}: {ledger_exc}", file=sys.stderr)


def ensure_traces(view, trace_paths, *, ledger=None, slice_id=None, counted=True, discard=False, make=None):
    """Produce or verify each trace path; returns [{'path', 'status': 'written'|'verified', 'elapsed_s'}]."""
    make = make or default_make
    results = []
    for trace_path in trace_paths:
        owner = view.trace_owner_by_path[trace_path]
        item_id = "trace-" + owner["id"]
        target = eio.inside(view.root, trace_path)
        stamp = utc_now()
        t0 = time.monotonic()
        if target.exists():
            try:
                same = eio.read(target) == make(owner["config"])
            except Exception:
                same = False
            if same:
                if ledger:
                    ledger.record("skipped", "trace", item_id, slice_id=slice_id, counted=counted,
                                  reason="verified_existing", elapsed_s=0.0)
                results.append({"path": trace_path, "status": "verified", "elapsed_s": 0.0})
                continue
            if not discard:
                raise TraceError(f"{trace_path} exists but differs from the regenerated trace (or is unreadable); "
                                 "refusing to overwrite; pass discard to delete and rewrite")
            target.unlink()
        if ledger:
            ledger.record("start", "trace", item_id, slice_id=slice_id, counted=counted, started_utc=stamp)
        recorded = False
        try:
            document = make(owner["config"])
            temp = target.with_name(target.name + f".tmp{os.getpid()}")
            eio.write(temp, document)
            try:
                os.link(temp, target)
            finally:
                temp.unlink()
            elapsed = time.monotonic() - t0
            if ledger:
                ledger.record("finish", "trace", item_id, slice_id=slice_id, counted=counted, started_utc=stamp,
                              finished_utc=utc_now(), elapsed_s=elapsed, exit_code=0, outcome="ok")
            recorded = True
        except (KeyboardInterrupt, SystemExit) as exc:
            if ledger and not recorded:
                _record_interrupted_trace(ledger, item_id, slice_id, counted, stamp, t0, exc)
            raise
        results.append({"path": trace_path, "status": "written", "elapsed_s": elapsed})
    return results


def main(argv=None):
    from . import plan_io, selector
    from .ledger import Ledger, describe_environment
    parser = argparse.ArgumentParser(description="produce the traces a slice needs (user-invoked)")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--slices", required=True)
    parser.add_argument("--slice", dest="slice_id", required=True)
    parser.add_argument("--env-label")
    parser.add_argument("--discard", action="store_true")
    args = parser.parse_args(argv)
    view = plan_io.load_for_execution(args.plan, args.revision)
    plan_io.mark_started(view)
    resolved = selector.resolve_all(view, selector.load_slices(args.slices))[args.slice_id]
    ledger = Ledger(args.ledger, plan_sha256=view.sha256, revision=view.revision,
                    source_sha256=view.source_hash, environment=describe_environment(args.env_label))
    try:
        rows = ensure_traces(view, resolved["trace_paths"], ledger=ledger, slice_id=args.slice_id,
                             counted=resolved["counted"], discard=args.discard)
    except OSError as exc:
        print(f"refused: {type(exc).__name__}: {exc}")
        return 4
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
