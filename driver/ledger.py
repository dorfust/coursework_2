"""Append-only JSONL elapsed-time ledger and ledger_sum (standard library only). Written, NOT run.

One line per event: start, finish, capped, skipped (plus refused, discarded). Elapsed seconds come from
time.monotonic() measured by the caller around the child process (finish/capped events carry them). A `finish` event
with outcome `interrupted` (cell or training unit stopped by KeyboardInterrupt / SIGTERM / SIGHUP) carries the elapsed
seconds too, so the sum does not under-count interrupted work.
The 'counted' flag is copied from slices.json (TRAIN/PILOT/B1B/E* true; B0 and installation are not
recorded here and are not counted, user decision R8_ADDENDUM_4 item 3; the user may change a flag).

Torn last line (R-4): before appending, Ledger.record checks the last byte of an existing non-empty file; if it is not a
newline (an earlier write was torn by a crash) a newline is written first, in the same write call, so the torn text stays
an unparsable line of its own (ledger_sum counts it in bad_lines) and the new event is never concatenated to it.

Sum (from the m1 directory):
  python -m driver.ledger sum LEDGER.jsonl [LEDGER2.jsonl ...] [--json]
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import sys
from pathlib import Path

LEDGER_SCHEMA = "ssn-m1-ledger-v1"
ELAPSED_EVENTS = ("finish", "capped")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _version(package):
    try:
        return importlib.metadata.version(package)
    except Exception:
        return None


def _proc_value(path, key):
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(key):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def describe_environment(label=None):
    """Environment record; versions via importlib.metadata (no import of torch), /proc read if present."""
    runner = os.environ.get("RUNNER_NAME")
    host = hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:12]
    ram = _proc_value("/proc/meminfo", "MemTotal")
    try:
        ram_kib = int(ram.split()[0]) if ram else None
    except ValueError:
        ram_kib = None
    return {"label": label or (f"runner:{runner}" if runner else f"host:{host}"),
            "hostname_sha256_12": host, "runner_name": runner,
            "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
            "os": platform.platform(), "python": platform.python_version(),
            "numpy": _version("numpy"), "torch": _version("torch"),
            "cpu_model": _proc_value("/proc/cpuinfo", "model name"),
            "logical_cpus": os.cpu_count(), "ram_kib": ram_kib}


def read_events(path):
    """Yield (event dict) per valid line; an unparsable line yields {'_bad_line': text}."""
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except ValueError:
                yield {"_bad_line": line.strip()[:80]}


class Ledger:
    def __init__(self, path, *, plan_sha256, revision, source_sha256, environment=None):
        self.path = Path(path)
        self.plan_sha256 = plan_sha256
        self.revision = revision
        self.source_sha256 = source_sha256
        self.environment = environment or describe_environment()

    def _env_minutes(self):
        label = self.environment["label"]
        total = 0.0
        for event in read_events(self.path):
            if event.get("event") in ELAPSED_EVENTS and event.get("environment", {}).get("label") == label:
                total += float(event.get("elapsed_s") or 0.0)
        return total / 60.0

    def _needs_newline(self):
        """True when the file exists, is non-empty and its last byte is not a newline (a torn last line)."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return False
        if size == 0:
            return False
        with self.path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) != b"\n"

    def record(self, event, kind, item_id, *, slice_id=None, counted=True, started_utc=None,
               finished_utc=None, elapsed_s=None, exit_code=None, **extra):
        line = {"schema": LEDGER_SCHEMA, "event": event, "kind": kind, "id": item_id, "slice": slice_id,
                "counted": counted, "started_utc": started_utc, "finished_utc": finished_utc,
                "logged_utc": utc_now(), "elapsed_s": elapsed_s, "exit_code": exit_code,
                "environment": self.environment, "plan_sha256": self.plan_sha256,
                "revision": self.revision, "source_sha256": self.source_sha256}
        line.update(extra)
        previous = self._env_minutes()
        line["cumulative_minutes_environment"] = previous + (
            float(elapsed_s or 0.0) / 60.0 if event in ELAPSED_EVENTS else 0.0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prefix = "\n" if self._needs_newline() else ""
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(prefix + json.dumps(line, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return line


def ledger_sum(paths):
    """Minutes by environment, by slice and kind, and the counted / not-counted split."""
    by_env, by_slice, by_kind = {}, {}, {}
    counted = not_counted = 0.0
    events = bad = 0
    for path in paths:
        for event in read_events(path):
            if "_bad_line" in event:
                bad += 1
                continue
            events += 1
            if event.get("event") not in ELAPSED_EVENTS:
                continue
            minutes = float(event.get("elapsed_s") or 0.0) / 60.0
            label = event.get("environment", {}).get("label", "unknown")
            by_env[label] = by_env.get(label, 0.0) + minutes
            by_slice[event.get("slice")] = by_slice.get(event.get("slice"), 0.0) + minutes
            by_kind[event.get("kind")] = by_kind.get(event.get("kind"), 0.0) + minutes
            if event.get("counted"):
                counted += minutes
            else:
                not_counted += minutes
    return {"events": events, "bad_lines": bad, "minutes_by_environment": by_env,
            "minutes_by_slice": by_slice, "minutes_by_kind": by_kind,
            "counted_minutes": counted, "not_counted_minutes": not_counted,
            "total_minutes": counted + not_counted}


def format_sum(summary):
    rows = [f"events {summary['events']} (unparsable lines {summary['bad_lines']})", "minutes by environment:"]
    rows += [f"  {k}: {v:.2f}" for k, v in sorted(summary["minutes_by_environment"].items())]
    rows.append("minutes by slice:")
    rows += [f"  {k}: {v:.2f}" for k, v in sorted(summary["minutes_by_slice"].items(), key=lambda kv: str(kv[0]))]
    rows.append("minutes by kind:")
    rows += [f"  {k}: {v:.2f}" for k, v in sorted(summary["minutes_by_kind"].items(), key=lambda kv: str(kv[0]))]
    rows.append(f"COUNTED {summary['counted_minutes']:.2f} min | NOT counted {summary['not_counted_minutes']:.2f} min | "
                f"total {summary['total_minutes']:.2f} min")
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="elapsed-time ledger tools")
    sub = parser.add_subparsers(dest="command", required=True)
    total = sub.add_parser("sum")
    total.add_argument("ledgers", nargs="+")
    total.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    summary = ledger_sum(args.ledgers)
    print(json.dumps(summary, indent=1, sort_keys=True) if args.json else format_sum(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
