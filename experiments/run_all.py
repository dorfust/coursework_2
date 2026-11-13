"""Single entry point for the plan -> train -> execute -> aggregate -> plot pipeline.

Runtime status: NOT executed by its authors. The first run by the user is the first test.

Usage (from the unpacked folder, for example in cmd):
    python experiments/run_all.py --config config.yaml --dry-run
    python experiments/run_all.py --config config.yaml --debug
    python experiments/run_all.py --config config.yaml
    python experiments/run_all.py --config config.yaml --output-root outputs/run_002

What it does: reads the config, checks it, and starts each requested stage as its own
process: [sys.executable, "-m", "ssn_hops.experiments", <stage>, ...]. It changes no file of
src/, driver/ or configs/, deletes nothing, overwrites nothing and cannot resume.
Standard library only (PyYAML is imported lazily and only for .yaml/.yml configs).

Exit codes:
    0    every requested stage finished with child exit code 0 (says nothing about validity)
    2    command-line or configuration error (also: the real argument parser rejected a command)
    3    pre-flight failure (missing package, existing output, path too long, probe failed)
    4    a stage failed (exit code of the stage and log location are printed)
    130  interrupted by Ctrl+C (the output of the interrupted stage is partial)
Any other exit code (for example 1 with a Python traceback) is an unexpected wrapper error.
"""
# Status wording of revision 5 (the docstring above is the earlier wording and is unchanged). By the user's report, an earlier form
# of this file was part of a tree that the user ran. After that run one constant of this file (DEFAULT_SUITE) and added comment
# lines were edited, and the edited file has not been executed. The statements below about the called code (the stage processes
# and the library) were read from this file only and were not compared with that code.
#
# Exit codes, as the code of this file sets them (additions to the table in the docstring above):
#   0    also the end of --dry-run: the pre-flight passed and no stage process was started.
#   2    ConfigError, raised by the config, stage-list, suite-semantics and command checks before the banner and the pre-flight
#        are printed; main also returns 2 for Python older than 3.10 before anything else. It covers the case that the real
#        argument parser rejects a built command (validate_with_real_parser).
#   3    PreflightError: pre-flight errors, or a failed probe (--check-imports, --debug). The text 'Nothing was started.' is
#        printed in both cases; the probe processes have already run when a probe fails, and with --debug the file run_all.log
#        is already open at that point.
#   4    a stage ended with a code other than 0, or its process could not be started (the code is then shown as -1);
#        the stages after it are not started.
#   130  KeyboardInterrupt caught in main, whenever it arrives inside run().
import argparse
import collections
import contextlib
import importlib.util
import io
import json
import locale
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# ROOT is the parent of the folder that holds this file (the file is expected at <project folder>/experiments/run_all.py);
# src/ is looked up as ROOT/src. Relative paths: the values of --config and --output-root go through Path(...).resolve() (the
# help text of --output-root says: relative to the current directory); the config keys suite, output_root and plan.models are
# joined to ROOT when they are not absolute (resolve_under_root). Stage and probe processes are started with ROOT as working directory.
ROOT = Path(__file__).resolve().parent.parent

STAGES = ("plan", "train", "execute", "aggregate", "plot")
STAGE_PREFIX = ["-m", "ssn_hops.experiments"]
REFERENCES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan",
              "TBR_bounded_exhaustive_reference", "TBR_enumeration")
NATIVE_REFERENCE = "TBR_bounded_exhaustive_reference"
ENUM_REFERENCE = "TBR_enumeration"
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
# Shape of the line that a stage process is expected to print when one of its jobs fails ('... exited <int>; preserve <log prefix> logs').
# The line is written by the called code; its shape is assumed here. report_failure searches the last OUTPUT_TAIL_LINES lines of the
# stage output, from the end, for the first line that matches and, when the prefix lies inside output_root, prints the last
# TAIL_LINES lines of <prefix>.stderr.txt. A prefix outside output_root is not read. Without a match only a general message is printed.
JOB_FAILED_PATTERN = re.compile(r"exited (-?[0-9]+); preserve (.+) logs\s*$")
# Meaning of the bare numbers and patterns around here. GRACE_S: seconds to wait for a stage after Ctrl+C. TAIL_LINES: lines of a
# failing job's stderr file that are printed. OUTPUT_TAIL_LINES: lines of stage output kept in memory to find the failing job.
# PROBE_TIMEOUT_S: seconds after which a probe process (import check, 'ssn_hops environment') counts as failed. REVISION_PATTERN:
# 40 lowercase hexadecimal characters; nothing else about a revision is checked here. STAGE_PREFIX: the arguments placed after
# sys.executable in full_command. The three path-length constants have their own comment below.
GRACE_S = 10
TAIL_LINES = 40
OUTPUT_TAIL_LINES = 300
# Windows path-length rule (applied only when os.name is 'nt'; see preflight_output). It measures len(str(<output_root>/plan)).
# LONGEST_RELATIVE_PATH: a fixed number written here, the assumed length that the longest file below the plan folder adds; this
# file does not compute it and does not state where it comes from. MAX_PATH_CHARS: the limit used by the check. Error (exit 3)
# when length + LONGEST_RELATIVE_PATH > MAX_PATH_CHARS (plan folder path longer than 174) and LongPathsEnabled is not confirmed
# as true (value false, absent or unreadable); otherwise a warning when length + LONGEST_RELATIVE_PATH > WARN_PATH_CHARS (longer
# than 115), also when long paths are enabled. summary.json and plots/ are not measured.
LONGEST_RELATIVE_PATH = 85
MAX_PATH_CHARS = 259
WARN_PATH_CHARS = 200
PROBE_TIMEOUT_S = 600

TOP_KEYS = ("revision", "suite", "output_root", "stages", "plan", "aggregate", "plot", "run")
SECTION_DEFAULTS = {
    "plan": {"models": None, "baselines_only": False, "include_native_tbr": False,
             "tbr_max_nodes": None, "tbr_max_expansions": None,
             "include_tbr_enumeration": False, "enum_max_call_expansions": None,
             "enum_max_cell_expansions": None},
    "aggregate": {"allow_partial": False, "reference": "TBR_style_hop_oracle"},
    "plot": {"allow_partial": False},
    "run": {"progress_interval_s": 60},
}
# Both constants below are used only when the config has no such key: normalize_config reads raw.get("suite", DEFAULT_SUITE)
# and raw.get("output_root", DEFAULT_OUTPUT_ROOT); --output-root replaces the output value afterwards. Relative values are
# joined to ROOT. DEFAULT_SUITE names the suite file configs/suite_paper_scope.json (sizes N = 132 to 396 in its grids).
# Earlier revisions of this file named a different suite file here. The suite files that start.py names for --quick and for the
# second run are configs/suite_quick.json and configs/suite_tbr_enumeration.json; start.py writes the key 'suite' into every
# config it generates, so a run through start.py does not use this default. The default output folder is <ROOT>/outputs/run_001;
# a plan folder that already exists there is refused by the pre-flight when the stage 'plan' is requested (nothing is deleted).
DEFAULT_SUITE = "configs/suite_paper_scope.json"
DEFAULT_OUTPUT_ROOT = "outputs/run_001"

# check_revision tests only the form of the revision (40 lowercase hexadecimal characters; the help text below asks for double
# quotes in YAML). The value is passed as --revision to the stages plan, train and execute (not to aggregate and plot). The code
# cannot tell a git commit SHA from another 40-character hexadecimal string and runs no git. start.py puts a content-derived string
# of this form into the config it generates unless --revision is given. What the called code does with the value is not described
# here. The help text speaks of a commit SHA of the downloaded state.
REVISION_HELP = (
    "The revision must be the 40-character lowercase hexadecimal commit SHA of the repository "
    "state you downloaded. Where to find it: open the repository page on GitHub, choose the "
    "branch you downloaded, click 'Commits' and copy the full SHA of the newest commit (copy "
    "button next to the commit). This script never runs git and never reads the zip file. "
    "In config.yaml put the SHA in double quotes (revision: \"<40 hex characters>\"): an "
    "unquoted value may be read by YAML as a number.")

INSTALL_HINTS = {
    "numpy": "pip install numpy",
    "torch": "pip install torch   (CPU build: use the selector on pytorch.org, Get Started, "
             "Windows, Pip, CPU)",
    "torch_geometric": "pip install torch-geometric   (see the PyG installation page)",
    "matplotlib": "pip install matplotlib   (or: pip install -e \".[plot]\")",
}


class ConfigError(Exception):
    """Command-line or configuration problem (exit code 2)."""


class PreflightError(Exception):
    """One or more pre-flight problems (exit code 3)."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = list(messages)


# The fields of Paths are absolute paths computed by derive_paths; models is None when plan.models is not set.
@dataclass(frozen=True)
class Paths:
    """Absolute paths derived from the config."""
    out: Path
    plan_dir: Path
    plan_json: Path
    summary: Path
    plots: Path
    suite: Path
    models: object  # Path or None


class Console:
    """Prints to stdout and, once a log file is open, appends the same text to it."""

    def __init__(self, keep_backlog):
        self.lock = threading.Lock()
        self.log = None
        self.backlog = [] if keep_backlog else None

    def say(self, text=""):
        """Print one line and tee it to the log (or remember it until the log opens)."""
        with self.lock:
            print(text, flush=True)
            if self.log is not None:
                self.log.write(text + "\n")
                self.log.flush()
            elif self.backlog is not None:
                self.backlog.append(text)

    def open_log(self, path):
        """Open the log file in append mode and write the lines printed so far."""
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.log = path.open("a", encoding="utf-8", errors="replace")
            for line in self.backlog or []:
                self.log.write(line + "\n")
            self.log.flush()
            self.backlog = None

    def close(self):
        """Close the log file if one is open."""
        with self.lock:
            if self.log is not None:
                self.log.close()
                self.log = None


def configure_streams():
    """Make the wrapper's own output tolerant of any console code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def format_elapsed(seconds):
    """Format seconds as HH:MM:SS."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return "%02d:%02d:%02d" % (hours, minutes, secs)


def is_inside(child, parent):
    """True when child is parent or lies below it (pure path comparison)."""
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------- configuration

def parse_cli(argv):
    """Parse the wrapper's own command line."""
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="Run plan, train, execute, aggregate and plot of ssn_hops.experiments.",
        epilog="Exit codes: 0 ok, 2 config/usage error, 3 pre-flight failure, "
               "4 a stage failed, 130 interrupted.")
    parser.add_argument("--config", required=True, help="path to config.yaml / config.json")
    parser.add_argument("--debug", action="store_true",
                        help="verbose report, import probes, run_all.log")
    parser.add_argument("--dry-run", action="store_true",
                        help="check everything and print the commands; execute nothing, create nothing")
    parser.add_argument("--stages", default=None,
                        help="comma list overriding the config key 'stages' (order is fixed)")
    parser.add_argument("--check-imports", action="store_true",
                        help="run a real import probe of the needed packages before the stages")
    parser.add_argument("--output-root", default=None,
                        help="folder for plan/, summary.json, plots/ and run_all.log; overrides the config "
                             "key output_root; a relative path is taken relative to the current directory "
                             "(like --config)")
    return parser.parse_args(argv)


def load_config(config_path):
    """Read the config file (yaml/yml/json) and return the normalised dictionary."""
    if not config_path.is_file():
        raise ConfigError("config file not found: " + ascii(str(config_path)))
    try:
        text = config_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError("cannot read the config as UTF-8 text: " + ascii(str(exc)))
    suffix = config_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ConfigError(
                "PyYAML is not installed, so a .yaml config cannot be read. Either run "
                "'pip install pyyaml' (or: pip install -e \".[yaml]\") or use the JSON twin: "
                "--config config.example.json")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError("the YAML config is not valid YAML: " + ascii(str(exc)))
    elif suffix == ".json":
        try:
            raw = json.loads(text)
        except ValueError as exc:
            raise ConfigError("the JSON config is not valid JSON: " + ascii(str(exc)))
    else:
        raise ConfigError("the config file name must end with .yaml, .yml or .json")
    return normalize_config(raw)


# Accepted values of the check_* functions. Flags: exactly true or false (type bool; 0, 1 and strings are refused). Budgets
# (tbr_max_*, enum_max_*): a positive integer or null; true, false and a float such as 5.0 are refused (the type must be int).
# Text values: a non-empty string, used with surrounding blanks removed. progress_interval_s: a finite number >= 0 that is not
# true or false, kept as a float; 0 means no heartbeat. Unknown keys are refused at the top level and inside every section; a
# section written as null counts as empty. Stage names are checked against STAGES and are always run in the fixed order of
# STAGES, whatever order the list has.
def check_text(value, label, allow_none=False):
    """Return a stripped non-empty string (or None when allowed)."""
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(label + " must be a non-empty string" + (" or null" if allow_none else ""))
    return value.strip()


def check_flag(value, label):
    """Return a bool; anything else is an error."""
    if type(value) is not bool:
        raise ConfigError(label + " must be true or false")
    return value


def check_budget(value, label):
    """Return a positive int or None."""
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ConfigError(label + " must be a positive integer or null")
    return value


def check_interval(value, label):
    """Return a finite non-negative number as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(label + " must be a number (0 switches the heartbeat off)")
    if not math.isfinite(value) or value < 0:
        raise ConfigError(label + " must be finite and not negative")
    return float(value)


def check_revision(value):
    """Return the revision if it is a 40-character lowercase hex string."""
    if not isinstance(value, str):
        raise ConfigError("revision must be a string (found type %s). %s"
                          % (type(value).__name__, REVISION_HELP))
    if not REVISION_PATTERN.fullmatch(value):
        raise ConfigError("revision is not a valid commit SHA (value starts with %s). %s"
                          % (ascii(value[:50]), REVISION_HELP))
    return value


def check_stages(value, label):
    """Return the stage names in the fixed pipeline order."""
    if not isinstance(value, list) or not value:
        raise ConfigError(label + " must be a non-empty list of stage names: " + ", ".join(STAGES))
    for item in value:
        if item not in STAGES:
            raise ConfigError("%s: unknown stage %s; allowed: %s" % (label, ascii(item), ", ".join(STAGES)))
    if len(set(value)) != len(value):
        raise ConfigError(label + " lists a stage twice")
    return [stage for stage in STAGES if stage in value]


def merged_section(raw, name):
    """Return the defaults of a section updated by the user's keys (unknown key = error)."""
    value = raw.get(name)
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigError("'%s' must be a mapping of keys" % name)
    unknown = sorted(ascii(key) for key in value if key not in SECTION_DEFAULTS[name])
    if unknown:
        raise ConfigError("unknown key(s) in '%s': %s; allowed: %s"
                          % (name, ", ".join(unknown), ", ".join(SECTION_DEFAULTS[name])))
    merged = dict(SECTION_DEFAULTS[name])
    merged.update(value)
    return merged


def normalize_config(raw):
    """Check keys and types of the raw config and return a complete dictionary."""
    if not isinstance(raw, dict):
        raise ConfigError("the config must be a mapping of keys at the top level")
    unknown = sorted(ascii(key) for key in raw if key not in TOP_KEYS)
    if unknown:
        raise ConfigError("unknown config key(s): %s; allowed: %s" % (", ".join(unknown), ", ".join(TOP_KEYS)))
    if "revision" not in raw:
        raise ConfigError("missing required key 'revision'. " + REVISION_HELP)
    plan = merged_section(raw, "plan")
    aggregate = merged_section(raw, "aggregate")
    plot = merged_section(raw, "plot")
    run = merged_section(raw, "run")
    reference = check_text(aggregate["reference"], "aggregate.reference")
    if reference not in REFERENCES:
        raise ConfigError("aggregate.reference must be one of: " + ", ".join(REFERENCES))
    return {
        "revision": check_revision(raw["revision"]),
        "suite": check_text(raw.get("suite", DEFAULT_SUITE), "suite"),
        "output_root": check_text(raw.get("output_root", DEFAULT_OUTPUT_ROOT), "output_root"),
        "stages": check_stages(raw.get("stages", list(STAGES)), "stages"),
        "plan": {
            "models": check_text(plan["models"], "plan.models", allow_none=True),
            "baselines_only": check_flag(plan["baselines_only"], "plan.baselines_only"),
            "include_native_tbr": check_flag(plan["include_native_tbr"], "plan.include_native_tbr"),
            "tbr_max_nodes": check_budget(plan["tbr_max_nodes"], "plan.tbr_max_nodes"),
            "tbr_max_expansions": check_budget(plan["tbr_max_expansions"], "plan.tbr_max_expansions"),
            "include_tbr_enumeration": check_flag(plan["include_tbr_enumeration"], "plan.include_tbr_enumeration"),
            "enum_max_call_expansions": check_budget(plan["enum_max_call_expansions"], "plan.enum_max_call_expansions"),
            "enum_max_cell_expansions": check_budget(plan["enum_max_cell_expansions"], "plan.enum_max_cell_expansions"),
        },
        "aggregate": {"allow_partial": check_flag(aggregate["allow_partial"], "aggregate.allow_partial"),
                      "reference": reference},
        "plot": {"allow_partial": check_flag(plot["allow_partial"], "plot.allow_partial")},
        "run": {"progress_interval_s": check_interval(run["progress_interval_s"], "run.progress_interval_s")},
    }


def stage_override(text):
    """Turn the --stages text into a validated stage list."""
    names = [part.strip() for part in text.split(",") if part.strip()]
    return check_stages(names, "--stages")


# If plan.baselines_only is true, 'train' is removed from the requested stages (from the config key or from --stages alike) and
# a NOTICE is printed; its text says that GLR is not planned and that execute needs no trained model, which is this file's
# statement about the called code and is not checked here. ConfigError 'no stage is left to run' if nothing remains. Everything
# after this function (semantic checks, package list, commands) uses the effective list.
def effective_stages(cfg, requested):
    """Apply the baselines_only rule; return (stage list, printed notices)."""
    stages = list(requested)
    notices = []
    if cfg["plan"]["baselines_only"] and "train" in stages:
        stages.remove("train")
        notices.append("plan.baselines_only is true: stage 'train' is skipped (GLR is not planned, "
                       "execute needs no trained model, and the code would train all models for nothing).")
    if not stages:
        raise ConfigError("no stage is left to run")
    return stages, notices


# Rules checked here (ConfigError, exit code 2), so that they are reported before any stage starts. The docstring says they mirror
# make_plan and aggregate; they were not compared with that code. Always: tbr_max_nodes and tbr_max_expansions need
# include_native_tbr; enum_max_call_expansions and enum_max_cell_expansions need include_tbr_enumeration; include_tbr_enumeration
# together with include_native_tbr is refused. Only when 'aggregate' is among the effective stages: reference GLR is refused with
# baselines_only; reference TBR_bounded_exhaustive_reference needs include_native_tbr; reference TBR_enumeration needs
# include_tbr_enumeration. Not checked here: whether the reference policy is planned for the chosen suite. check_suite_semantics
# (include_native_tbr together with a suite that has the key policy_scope) runs only when the stage 'plan' is requested and the
# suite file could be read.
def check_semantics(cfg, stages):
    """Checks that mirror make_plan and aggregate so the user hears about them early."""
    plan = cfg["plan"]
    reference = cfg["aggregate"]["reference"]
    if not plan["include_native_tbr"] and (plan["tbr_max_nodes"] is not None
                                           or plan["tbr_max_expansions"] is not None):
        raise ConfigError("plan.tbr_max_nodes / plan.tbr_max_expansions need plan.include_native_tbr: true")
    enum_budgets = (plan["enum_max_call_expansions"], plan["enum_max_cell_expansions"])
    if not plan["include_tbr_enumeration"] and any(value is not None for value in enum_budgets):
        raise ConfigError("plan.enum_max_call_expansions / plan.enum_max_cell_expansions need "
                          "plan.include_tbr_enumeration: true")
    if plan["include_tbr_enumeration"] and plan["include_native_tbr"]:
        raise ConfigError("plan.include_tbr_enumeration is refused together with plan.include_native_tbr "
                          "(make_plan does not plan both)")
    if "aggregate" in stages:
        if plan["baselines_only"] and reference == "GLR":
            raise ConfigError("aggregate.reference GLR is impossible with plan.baselines_only: true "
                              "(GLR is not planned)")
        if reference == NATIVE_REFERENCE and not plan["include_native_tbr"]:
            raise ConfigError("aggregate.reference " + NATIVE_REFERENCE + " needs plan.include_native_tbr: true")
        if reference == ENUM_REFERENCE and not plan["include_tbr_enumeration"]:
            raise ConfigError("aggregate.reference " + ENUM_REFERENCE + " needs plan.include_tbr_enumeration: true")


def check_suite_semantics(cfg, suite):
    """Refuse include_native_tbr together with a suite that has the key policy_scope."""
    if cfg["plan"]["include_native_tbr"] and "policy_scope" in suite:
        raise ConfigError("plan.include_native_tbr is refused with this suite: it has the key "
                          "policy_scope, and native plans do not support policy_scope "
                          "(the native plan schema is frozen). Set include_native_tbr to false.")


# The suite file is opened with encoding utf-8 and the message says 'without BOM'; the config file itself is read with utf-8-sig
# (load_config). The claim 'like the real code does' in the docstring was not compared with the called code.
def load_suite(path):
    """Read the suite JSON like the real code does (UTF-8, no BOM). Return (dict or None, problem or None)."""
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, "suite file not found: " + str(path)
    except (OSError, ValueError) as exc:
        return None, "suite file cannot be read as UTF-8 JSON without BOM: %s (%s)" % (path, exc)
    if not isinstance(data, dict):
        return None, "suite file is not a JSON object: " + str(path)
    return data, None


def resolve_under_root(text):
    """Resolve a config path: relative paths are taken relative to the project folder ROOT."""
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def derive_paths(cfg):
    """Compute every absolute path used by the stage commands."""
    out = resolve_under_root(cfg["output_root"])
    models = cfg["plan"]["models"]
    return Paths(out=out, plan_dir=out / "plan", plan_json=out / "plan" / "plan.json",
                 summary=out / "summary.json", plots=out / "plots",
                 suite=resolve_under_root(cfg["suite"]),
                 models=resolve_under_root(models) if models else None)


# ---------------------------------------------------------------- commands

# Mapping of the config to the arguments (validate_with_real_parser passes them to the real parser of ssn_hops.experiments).
# plan: --suite, --out <output_root>/plan, --revision; then, only when set: --models (plan.models), --baselines-only,
# --include-native-tbr, --tbr-max-nodes, --tbr-max-expansions, --include-tbr-enumeration, --enum-max-call-expansions,
# --enum-max-cell-expansions. A budget that is null gives no flag; what the called code then uses is decided there.
# train and execute: --plan <output_root>/plan/plan.json --revision. aggregate: --plan, --out <output_root>/summary.json,
# --allow-partial (when aggregate.allow_partial) and always --reference <aggregate.reference>. plot: --summary,
# --out <output_root>/plots, --allow-partial (when plot.allow_partial). --revision is not passed to aggregate and plot.
# All paths come from derive_paths (absolute).
def stage_args(stage, cfg, paths):
    """Arguments after 'python -m ssn_hops.experiments' for one stage (checked by the real parser)."""
    revision = cfg["revision"]
    plan = cfg["plan"]
    if stage == "plan":
        argv = ["plan", "--suite", str(paths.suite), "--out", str(paths.plan_dir), "--revision", revision]
        if paths.models is not None:
            argv += ["--models", str(paths.models)]
        if plan["baselines_only"]:
            argv.append("--baselines-only")
        if plan["include_native_tbr"]:
            argv.append("--include-native-tbr")
        if plan["tbr_max_nodes"] is not None:
            argv += ["--tbr-max-nodes", str(plan["tbr_max_nodes"])]
        if plan["tbr_max_expansions"] is not None:
            argv += ["--tbr-max-expansions", str(plan["tbr_max_expansions"])]
        if plan["include_tbr_enumeration"]:
            argv.append("--include-tbr-enumeration")
        if plan["enum_max_call_expansions"] is not None:
            argv += ["--enum-max-call-expansions", str(plan["enum_max_call_expansions"])]
        if plan["enum_max_cell_expansions"] is not None:
            argv += ["--enum-max-cell-expansions", str(plan["enum_max_cell_expansions"])]
        return argv
    if stage in ("train", "execute"):
        return [stage, "--plan", str(paths.plan_json), "--revision", revision]
    if stage == "aggregate":
        argv = ["aggregate", "--plan", str(paths.plan_json), "--out", str(paths.summary)]
        if cfg["aggregate"]["allow_partial"]:
            argv.append("--allow-partial")
        argv += ["--reference", cfg["aggregate"]["reference"]]
        return argv
    argv = ["plot", "--summary", str(paths.summary), "--out", str(paths.plots)]
    if cfg["plot"]["allow_partial"]:
        argv.append("--allow-partial")
    return argv


def build_stage_argvs(cfg, stages, paths):
    """List of (stage, argument list after the prefix) in pipeline order."""
    return [(stage, stage_args(stage, cfg, paths)) for stage in stages]


def full_command(argv):
    """Complete argv of a stage process."""
    return [sys.executable] + STAGE_PREFIX + argv


def validate_with_real_parser(argvs):
    """Run every argument list through ssn_hops.experiments.parser(); mismatch = ConfigError."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    # The wrapper imports the package in its own process: do not leave .pyc files in src/ssn_hops.
    sys.dont_write_bytecode = True
    try:
        from ssn_hops.experiments import parser as real_parser_factory
    except ImportError as exc:
        raise ConfigError("cannot import ssn_hops.experiments from %s (is the folder src/ssn_hops "
                          "present next to experiments/?): %s" % (src, exc))
    real_parser = real_parser_factory()
    for stage, argv in argvs:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stderr(captured), contextlib.redirect_stdout(captured):
                real_parser.parse_args(argv)
        except SystemExit:
            lines = [line for line in captured.getvalue().splitlines() if line.strip()]
            reason = lines[-1] if lines else "no message"
            raise ConfigError("stage %s: the real argument parser of ssn_hops.experiments rejected "
                              "the command: %s" % (stage, reason))


# Every stage and probe process gets the same interpreter as this script (sys.executable), ROOT as working directory, stdout and
# stderr merged into one pipe (read as UTF-8, undecodable bytes replaced) and a copy of this process's environment with these
# changes: PYTHONPATH = ROOT/src (an existing PYTHONPATH follows after os.pathsep, so ROOT/src is listed first); PYTHONUTF8=1,
# PYTHONIOENCODING=utf-8, PYTHONUNBUFFERED=1; with --debug also PYTHONFAULTHANDLER=1. PYTHONDONTWRITEBYTECODE is not among them;
# sys.dont_write_bytecode is set to True in validate_with_real_parser, which affects this process only.
def env_overrides(debug):
    """The environment variables the wrapper sets for every stage process."""
    src = str(ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    values = {"PYTHONPATH": src + os.pathsep + existing if existing else src,
              "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    if debug:
        values["PYTHONFAULTHANDLER"] = "1"
    return values


def build_env(debug):
    """Copy of the current environment plus the overrides."""
    env = dict(os.environ)
    env.update(env_overrides(debug))
    return env


# ---------------------------------------------------------------- pre-flight

def long_paths_enabled():
    """True/False from the registry value LongPathsEnabled; None when unknown or not Windows."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            value, _kind = winreg.QueryValueEx(key, "LongPathsEnabled")
        return bool(value)
    except FileNotFoundError:
        return False
    except (ImportError, OSError):
        return None


# Package names the effective stages need, without duplicates: 'execute' needs numpy and torch; 'train', or 'execute' without
# baselines_only, also torch_geometric; 'plot' needs matplotlib; 'plan' and 'aggregate' need none. The table is fixed in this
# function and is not derived from the called code. This script itself imports ssn_hops.experiments in validate_with_real_parser;
# what that module loads is not described here. run_probes runs an import probe of these names when --check-imports or --debug
# is given (a failed probe is exit 3), and 'python -m ssn_hops environment' only with --debug and when torch_geometric is needed.
def required_modules(stages, baselines_only):
    """Top-level packages the requested stages import (the wrapper itself imports none)."""
    modules = []
    if "execute" in stages:
        modules += ["numpy", "torch"]
    if "train" in stages or ("execute" in stages and not baselines_only):
        modules += ["numpy", "torch", "torch_geometric"]
    if "plot" in stages:
        modules.append("matplotlib")
    return list(dict.fromkeys(modules))


def module_missing(name):
    """True when find_spec says the package is absent (nothing is imported)."""
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return True


def synced_folder(path):
    """True when the path looks like a cloud-synchronised folder (OneDrive, Dropbox)."""
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith("onedrive") or lowered.startswith("dropbox"):
            return True
    for key, value in os.environ.items():
        if key.upper().startswith("ONEDRIVE") and value and is_inside(path, Path(value)):
            return True
    return False


# Stage 'plan' requested: the suite file must be readable as a JSON object (load_suite); its keys core_template and
# simulation_template must be file names of files in the folder of the suite file; plan.models, when set, must be a file;
# <output_root>/plan must not exist. Stage 'plan' not requested: <output_root>/plan/plan.json must exist when 'train', 'execute'
# or 'aggregate' is requested. 'aggregate': summary.json must not exist. 'plot': <output_root>/plots must not exist and, without
# 'aggregate', summary.json must exist. Nothing else inside plan/ is checked. Every problem found here is an error (exit 3).
def preflight_inputs(stages, paths, suite_result, errors):
    """Existing/missing files for the requested stages."""
    suite, problem = suite_result
    if "plan" in stages:
        if problem:
            errors.append(problem)
        else:
            for key in ("core_template", "simulation_template"):
                name = suite.get(key)
                if not isinstance(name, str) or not name:
                    errors.append("suite key %s must be a file name" % key)
                elif not (paths.suite.parent / name).is_file():
                    errors.append("suite template file not found: " + str(paths.suite.parent / name))
        if paths.models is not None and not paths.models.is_file():
            errors.append("plan.models file not found: " + str(paths.models))
        if paths.plan_dir.exists():
            errors.append("plan folder already exists: %s (the code refuses existing outputs; this script never "
                          "deletes: choose another output_root (config key or --output-root) or remove the folder yourself)" % paths.plan_dir)
    elif any(stage in stages for stage in ("train", "execute", "aggregate")) and not paths.plan_json.is_file():
        errors.append("plan.json not found: %s (run the stage 'plan' first)" % paths.plan_json)
    if "aggregate" in stages and paths.summary.exists():
        errors.append("summary.json already exists: %s (the code refuses to overwrite)" % paths.summary)
    if "plot" in stages:
        if paths.plots.exists():
            errors.append("plots folder already exists: %s (the code refuses to overwrite)" % paths.plots)
        if "aggregate" not in stages and not paths.summary.is_file():
            errors.append("summary.json not found: %s (run the stage 'aggregate' first)" % paths.summary)


def preflight_output(stages, paths, errors, warnings):
    """Output folder location and Windows path-length budget."""
    if not Path(paths.out.anchor).exists():
        errors.append("the drive or root of output_root does not exist: " + paths.out.anchor)
    if paths.out.exists() and not paths.out.is_dir():
        errors.append("output_root exists and is not a folder: " + str(paths.out))
    # output_root may not lie inside one of these folders of the project (the reason is not stated in this file). Not refused by
    # this loop: ROOT itself and every other folder, for example ROOT/outputs. Also refused above: a drive or root that does not
    # exist, and an existing output_root that is not a folder.
    for name in ("src", ".venv", "configs", "driver", "docs", "experiments", ".vscode"):
        if is_inside(paths.out, ROOT / name):
            errors.append("output_root must not be inside %s" % (ROOT / name))
    if os.name == "nt":
        length = len(str(paths.plan_dir))
        if length + LONGEST_RELATIVE_PATH > MAX_PATH_CHARS and long_paths_enabled() is not True:
            errors.append("the plan folder path has %d characters; the longest planned file adds about %d, "
                          "which exceeds the %d characters of the classic Windows path limit and long paths "
                          "are not confirmed enabled. Use a shorter output_root (for example C:\\w\\r1)."
                          % (length, LONGEST_RELATIVE_PATH, MAX_PATH_CHARS))
        elif length + LONGEST_RELATIVE_PATH > WARN_PATH_CHARS:
            warnings.append("the plan folder path has %d characters; a shorter output_root is safer" % length)


def preflight_packages(stages, cfg, errors):
    """Packages that must be importable (presence only; --check-imports tests a real import)."""
    for name in required_modules(stages, cfg["plan"]["baselines_only"]):
        if module_missing(name):
            errors.append("package '%s' is not installed for %s. Install: %s"
                          % (name, sys.executable, INSTALL_HINTS[name]))


# Errors (exit 3) come from the three helper functions preflight_inputs (files and folders that must or must not exist),
# preflight_output (output location, Windows path length) and preflight_packages (a package that module_missing reports as
# absent), and from Python older than 3.10. Warnings are printed and never stop the run: Python 3.15 or newer; GLR planned,
# 'execute' requested without 'train' and plan.models not set; plan.models set although baselines_only is true;
# include_native_tbr together with aggregate or plot; ROOT or output_root under a cloud-synchronised folder (a path part starting
# with 'onedrive' or 'dropbox' in any letter case, or a path inside a folder named by an environment variable whose name starts
# with ONEDRIVE; no other service is tested); a path with spaces or non-ASCII characters; a python.exe path containing
# WindowsApps (only on Windows, letter case as written); no virtual environment (sys.prefix equals sys.base_prefix).
def preflight(cfg, stages, paths, suite_result):
    """Collect (errors, warnings) without writing anything."""
    errors = []
    warnings = []
    # The same version test is made in main, which returns exit code 2 before run (and so preflight) is reached; by reading, this
    # branch is not reached when preflight is called from run. The reason for the second test is not stated in this file.
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or newer is required; this is " + platform.python_version())
    elif sys.version_info >= (3, 15):
        warnings.append("Python %s is newer than the declared range (pyproject: <3.15)" % platform.python_version())
    preflight_inputs(stages, paths, suite_result, errors)
    preflight_output(stages, paths, errors, warnings)
    preflight_packages(stages, cfg, errors)
    plan = cfg["plan"]
    if "plan" in stages and "execute" in stages and "train" not in stages \
            and not plan["baselines_only"] and plan["models"] is None:
        warnings.append("GLR is planned but the stage 'train' is not requested and plan.models is not set: "
                        "execute will fail unless trained models already exist")
    if plan["baselines_only"] and plan["models"] is not None:
        warnings.append("plan.models is set but baselines_only is true: the models are not used")
    if plan["include_native_tbr"] and ("aggregate" in stages or "plot" in stages):
        warnings.append("native plans are marked as aggregation/plots unsupported in the plan metadata; "
                        "the stages aggregate/plot may refuse them")
    for label, path in (("project folder", ROOT), ("output_root", paths.out)):
        if synced_folder(path):
            warnings.append("%s looks like a cloud-synchronised folder (OneDrive/Dropbox); file locks can "
                            "break long runs: %s" % (label, path))
        text = str(path)
        if not text.isascii() or " " in text:
            warnings.append("%s contains spaces or non-ASCII characters (handled by the code by reading, "
                            "never tested); a short ASCII path is safer: %s" % (label, ascii(text)))
    if os.name == "nt" and "WindowsApps" in sys.executable:
        warnings.append("python.exe comes from WindowsApps (Microsoft Store); a python.org installation is safer")
    if sys.prefix == sys.base_prefix:
        warnings.append("Python is not running inside a virtual environment (.venv)")
    return errors, warnings


def print_debug_header(console, paths):
    """Facts about the interpreter and the paths (no full environment dump)."""
    long_paths = long_paths_enabled()
    console.say("--- debug report ---")
    console.say("python: %s (%s)" % (platform.python_version(), platform.python_implementation()))
    console.say("platform: " + platform.platform())
    console.say("sys.executable: " + sys.executable)
    console.say("preferred encoding: %s; utf8_mode flag: %s" % (locale.getpreferredencoding(False), sys.flags.utf8_mode))
    console.say("ROOT: " + str(ROOT))
    console.say("output_root: " + str(paths.out))
    console.say("plan folder path length: %d (longest relative path assumed: %d, classic limit %d)"
                % (len(str(paths.plan_dir)), LONGEST_RELATIVE_PATH, MAX_PATH_CHARS))
    console.say("LongPathsEnabled: " + ("unknown or not Windows" if long_paths is None else str(long_paths)))
    console.say("environment variables set for every stage process:")
    for key, value in env_overrides(True).items():
        console.say("  %s=%s" % (key, value))


# The commands are shown with subprocess.list2cmdline on every operating system; the processes are started from the argument
# list, not from this text.
def print_commands(console, argvs, debug):
    """Print the commands exactly as they would be run."""
    console.say("Commands in order (%d):" % len(argvs))
    for number, (stage, argv) in enumerate(argvs, 1):
        command = full_command(argv)
        console.say("[%d] %s: %s" % (number, stage, subprocess.list2cmdline(command)))
        if debug:
            console.say("    argv list: " + repr(command))


# ---------------------------------------------------------------- running

def run_probe(command, label, env, console):
    """Run a short diagnostic process, show its output, return True when its exit code is 0."""
    console.say("probe: " + label)
    console.say("command: " + subprocess.list2cmdline(command))
    try:
        done = subprocess.run(command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                              timeout=PROBE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        console.say("probe timed out after %d s" % PROBE_TIMEOUT_S)
        return False
    except OSError as exc:
        console.say("probe could not be started: %s" % exc)
        return False
    for line in done.stdout.splitlines():
        console.say("  " + line)
    console.say("probe exit code: %d" % done.returncode)
    return done.returncode == 0


def run_probes(args, stages, cfg, env, console):
    """Import probe (--check-imports or --debug) and, in --debug, 'python -m ssn_hops environment'."""
    baselines_only = cfg["plan"]["baselines_only"]
    modules = required_modules(stages, baselines_only)
    if modules and (args.check_imports or args.debug):
        code = "import " + ", ".join(modules) + "; print('imports ok: " + ", ".join(modules) + "')"
        if not run_probe([sys.executable, "-c", code], "import check", env, console):
            raise PreflightError(["the import probe failed: a package is installed but cannot be imported "
                                  "(see the output above)"])
    needs_geometric = "train" in stages or ("execute" in stages and not baselines_only)
    if args.debug and needs_geometric:
        if not run_probe([sys.executable, "-m", "ssn_hops", "environment"], "ssn_hops environment", env, console):
            raise PreflightError(["'python -m ssn_hops environment' failed (see the output above)"])


def read_expected_jobs(plan_json, stage):
    """Number of jobs of the stage according to plan.json, or None if it cannot be read."""
    try:
        with plan_json.open(encoding="utf-8") as handle:
            body = json.load(handle)["body"]
        if stage == "execute":
            return len(body["cells"])
        return sum(len(item["steps"]) for item in body["models"].values() if not item["supplied"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def count_status_files(logs_dir, stage):
    """Count job status files by name only: cell jobs start with 's-', training jobs do not."""
    try:
        names = os.listdir(str(logs_dir))
    except OSError:
        return 0
    count = 0
    for name in names:
        if name.endswith(".status.json") and (stage == "execute") == name.startswith("s-"):
            count += 1
    return count


# Heartbeat: every interval seconds (config key run.progress_interval_s, default 60; with 0 no thread is started) one
# '[heartbeat]' line is printed; run_stage uses it for the stages 'train' and 'execute' only. It counts the files
# <output_root>/plan/logs/*.status.json by name: for 'execute' those whose name starts with 's-', for 'train' those whose name
# does not. The total is the number of cells (execute) or the number of steps of the models that are not supplied (train), read
# once from plan.json after the first interval and shown as '?' if it could not be read. A failed job also has a status file, so
# the count is not a measure of success or of progress inside a job. The file naming and the layout of plan.json are assumptions
# of this file about the called code.
class Heartbeat:
    """Daemon thread that periodically prints how many job status files exist."""

    def __init__(self, console, stage, paths, interval):
        self.console = console
        self.stage = stage
        self.paths = paths
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.started = time.monotonic()
        self.total = None
        self.total_read = False

    def start(self):
        """Start the thread unless the interval is 0."""
        if self.interval > 0:
            self.thread.start()

    def stop(self):
        """Ask the thread to end and wait briefly."""
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2)

    def loop(self):
        """Print one line per interval until stopped."""
        while not self.stop_event.wait(self.interval):
            if not self.total_read:
                self.total = read_expected_jobs(self.paths.plan_json, self.stage)
                self.total_read = True
            done = count_status_files(self.paths.plan_dir / "logs", self.stage)
            total = "?" if self.total is None else str(self.total)
            self.console.say("[heartbeat] %s: %d of %s jobs have a status file (failed ones included), elapsed %s"
                             % (self.stage, done, total, format_elapsed(time.monotonic() - self.started)))


# Ctrl+C: stop_process waits GRACE_S seconds for the stage to end by itself (a second Ctrl+C ends the wait at once); if the stage
# has not ended, kill_tree runs. On Windows it runs 'taskkill /PID <pid> /T /F' (its arguments include /T and /F) and then
# proc.kill() if the stage process is still alive; on other systems it runs only proc.kill() on the stage process itself, and
# this code sends nothing to its children. After that up to 10 seconds are waited and a warning is printed if the end is not
# confirmed. The messages say 'process tree' on every system.
def kill_tree(proc, console):
    """End the stage process and its children: taskkill /T /F on Windows, proc.kill() as fallback."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            console.say("taskkill could not be used: %s" % exc)
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        console.say("warning: the stage process did not confirm that it ended (pid %d)" % proc.pid)


def stop_process(proc, console):
    """Give the stage a grace period after Ctrl+C, then end its process tree."""
    console.say("Interrupt received: waiting up to %d s for the stage to stop (press Ctrl+C again to end it now)"
                % GRACE_S)
    try:
        proc.wait(timeout=GRACE_S)
        return
    except subprocess.TimeoutExpired:
        console.say("The stage did not stop in time: ending its process tree")
    except KeyboardInterrupt:
        console.say("Second interrupt: ending the process tree now")
    kill_tree(proc, console)


def run_stage(stage, argv, env, cfg, paths, args, console):
    """Run one stage, tee its output, return (exit code, last output lines)."""
    command = full_command(argv)
    console.say("")
    console.say("=== stage %s: start ===" % stage)
    console.say("command: " + subprocess.list2cmdline(command))
    if args.debug:
        console.say("argv list: " + repr(command))
    tail = collections.deque(maxlen=OUTPUT_TAIL_LINES)
    try:
        proc = subprocess.Popen(command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as exc:
        console.say("the stage process could not be started: %s" % exc)
        return -1, []
    started = time.monotonic()
    heartbeat = None
    if stage in ("train", "execute"):
        heartbeat = Heartbeat(console, stage, paths, cfg["run"]["progress_interval_s"])
        heartbeat.start()
    try:
        for line in proc.stdout:
            text = line.rstrip("\r\n")
            tail.append(text)
            console.say(text)
        code = proc.wait()
    except KeyboardInterrupt:
        stop_process(proc, console)
        raise
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        proc.stdout.close()
    console.say("=== stage %s: exit code %d after %s ===" % (stage, code, format_elapsed(time.monotonic() - started)))
    return code, list(tail)


def read_tail(path, count):
    """Last lines of a text file (UTF-8, errors replaced) or None when it cannot be read."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\r\n") for line in collections.deque(handle, maxlen=count)]
    except OSError:
        return None


def report_failure(stage, code, tail, paths, console):
    """Print the failure summary and the stderr tail of the failing job, when it can be found."""
    shown = str(code)
    if os.name == "nt" and code > 0xFFFF:
        shown += " (0x%08X)" % (code & 0xFFFFFFFF)
    console.say("")
    console.say("STAGE FAILED: %s exited with code %s" % (stage, shown))
    console.say("Logs of the jobs: " + str(paths.plan_dir / "logs"))
    for line in reversed(tail):
        match = JOB_FAILED_PATTERN.search(line)
        if match is None:
            continue
        prefix = Path(match.group(2))
        if not is_inside(prefix, paths.out):
            console.say("The failing job reports a log prefix outside output_root; it is not read: " + ascii(str(prefix)))
            return
        stderr_path = Path(str(prefix) + ".stderr.txt")
        lines = read_tail(stderr_path, TAIL_LINES)
        if lines is None:
            console.say("The stderr file of the failing job could not be read: " + str(stderr_path))
            return
        console.say("--- last %d lines of %s ---" % (TAIL_LINES, stderr_path))
        for text in lines:
            console.say(text)
        console.say("--- end of stderr tail ---")
        return
    console.say("No failing job was named in the output (see the lines above; run with --debug for a log file).")


# ---------------------------------------------------------------- main flow

# Order of run: (1) read the config, check it, the stage list, the semantic rules and the suite, build the commands and pass
# them to the real parser of ssn_hops.experiments (which imports that module into this process); a ConfigError here is exit 2
# and no banner is printed. (2) The banner; with --debug also the debug header. (3) The pre-flight (exit 3), also with
# --dry-run. (4) With --dry-run: print the commands and return 0; no probe and no stage runs, this script creates no file or
# folder, and --check-imports has no effect. (5) With --debug: open <output_root>/run_all.log in append mode (UTF-8; output_root
# and its parents are created if missing) and write the lines printed so far; a run that ends in steps (1) to (3) therefore
# leaves no run_all.log of its own. (6) The probes, with --check-imports or --debug. (7) The stages in order, stopping at the
# first failure (exit 4). This script creates only run_all.log itself; plan/, plan/plan.json, plan/logs, summary.json and
# plots/ are written by the stage processes (the called code, not read here). This file contains no call that deletes anything.
def run(args, console):
    """Whole run; returns the exit code or raises ConfigError / PreflightError / KeyboardInterrupt."""
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    requested = stage_override(args.stages) if args.stages is not None else cfg["stages"]
    stages, notices = effective_stages(cfg, requested)
    check_semantics(cfg, stages)
    if args.output_root is not None:
        cfg["output_root"] = str(Path(check_text(args.output_root, "--output-root")).resolve())
    paths = derive_paths(cfg)
    suite_result = load_suite(paths.suite) if "plan" in stages else (None, None)
    if suite_result[0] is not None:
        check_suite_semantics(cfg, suite_result[0])
    argvs = build_stage_argvs(cfg, stages, paths)
    validate_with_real_parser(argvs)

    # Status lines. The first line is a fixed text, not the result of any check; for the status of the edited file see the
    # comment after the module docstring. 'Pre-flight checks passed' means that files, folders and package presence were inspected
    # (module_missing). The final 'All requested stages ended with child exit code 0 after HH:MM:SS' counts the stage processes
    # only (the clock starts after the probes) and says nothing about the validity of the results.
    console.say("run_all.py (runtime status: not tested by its authors)")
    console.say("config: " + str(config_path))
    console.say("project folder: " + str(ROOT))
    console.say("output folder: " + str(paths.out))
    console.say("stages: " + ", ".join(stages))
    for notice in notices:
        console.say("NOTICE: " + notice)
    if args.debug:
        print_debug_header(console, paths)
    errors, warnings = preflight(cfg, stages, paths, suite_result)
    for warning in warnings:
        console.say("WARNING: " + warning)
    if errors:
        raise PreflightError(errors)
    console.say("Pre-flight checks passed (by inspection of files and package presence only).")

    if args.dry_run:
        console.say("")
        print_commands(console, argvs, args.debug)
        console.say("Environment set for every stage process: " + ", ".join(sorted(env_overrides(args.debug))))
        console.say("Nothing was executed. No file or folder was created.")
        return 0

    if args.debug:
        console.open_log(paths.out / "run_all.log")
        console.say("--- log: %s (append, UTF-8) ---" % (paths.out / "run_all.log"))
        print_commands(console, argvs, True)
    env = build_env(args.debug)
    run_probes(args, stages, cfg, env, console)

    started = time.monotonic()
    for stage, argv in argvs:
        code, tail = run_stage(stage, argv, env, cfg, paths, args, console)
        if code != 0:
            report_failure(stage, code, tail, paths, console)
            return 4
    console.say("")
    console.say("All requested stages ended with child exit code 0 after %s. This says nothing about "
                "the scientific validity of the results." % format_elapsed(time.monotonic() - started))
    return 0


def main(argv=None):
    """Entry point; returns the process exit code."""
    if sys.version_info < (3, 10):
        print("CONFIG ERROR: Python 3.10 or newer is required; this is " + platform.python_version())
        return 2
    configure_streams()
    args = parse_cli(argv)
    console = Console(keep_backlog=args.debug and not args.dry_run)
    try:
        return run(args, console)
    except ConfigError as exc:
        console.say("CONFIG ERROR: %s" % exc)
        return 2
    except PreflightError as exc:
        for message in exc.messages:
            console.say("PRE-FLIGHT PROBLEM: %s" % message)
        console.say("Nothing was started.")
        return 3
    except KeyboardInterrupt:
        console.say("")
        console.say("Interrupted. The output of the interrupted stage is partial and no stage can resume. "
                    "To start again, delete the output folder by hand (this script never deletes) or choose "
                    "another output_root.")
        return 130
    finally:
        console.close()


if __name__ == "__main__":
    sys.exit(main())
