"""One-command start of the ssn_hops pipeline (revision 5; staging copy of REV4/start.py).

Run status: this file does not state it, because a status written into a source file goes stale;
see the section on status in README.md.
Standard library only; the syntax is kept simple so that the version check below can print
its hint even on an old Python 3 (no f-strings, no annotations).

Usage (from the unpacked project folder, normally through run.cmd, which picks a Python):
    run.cmd                                  full run, paper scope (about 5 hours, an ESTIMATE)
    run.cmd --quick                          smoke test, the numbers are NOT results
    run.cmd --tbr-enumeration                full run, then a SECOND run with TBR_enumeration
    run.cmd --tbr-enumeration --skip-main    only the second run
    run.cmd --models <folder of an earlier run>   reuse already trained models
    run.cmd --dry-run
    run.cmd --stages plan
    python start.py [options]
In VS Code: open start.py (full run), start_quick.py, start_tbr_enumeration.py or
start_dry_run.py and press Run Python File; each one calls main() of this file.

What it does, in this order:
  1. checks that this Python is 3.10 up to 3.14; if not, it starts itself again with a suitable
     Python that it finds (.venv, then py -3.14 .. py -3.10 on Windows, python3.14 .. python3.10
     on POSIX) and passes the exit code on; only when none is found: exit code 11 with an install hint;
  2. computes a content-derived 40-hex revision string (NOT a git commit) or takes --revision;
  3. reads config.example.json (the JSON twin of config.yaml) and checks that it is usable;
  4. when .venv/ssn_ready.json is missing: creates .venv if needed, upgrades pip, installs the CPU
     build of torch and 'pip install -e ".[plot]"', runs the import probe and writes the marker;
     when the marker exists: only the same import probe (use --no-setup to skip even that);
  5. writes a NEW JSON config under outputs/_start/ (the base config is never changed): the suite
     is configs/suite_paper_scope.json (CGR on every cell, N up to 396), or configs/suite_quick.json
     with --quick;
  6. starts experiments/run_all.py with --config <that file>, with --debug unless --quiet, and with --dry-run if given;
  7. after a successful main run that produced summary.json (not with --quick): runs
     experiments/paper_style_plots.py when that file exists (guarded: a failure there never
     hides the result of run_all.py);
  8. with --tbr-enumeration: after a successful main run (or alone with --skip-main) a SECOND
     run_all.py call with its own generated config (suite configs/suite_tbr_enumeration.json,
     baselines only plus the optional policy TBR_enumeration, with safety budgets); after a
     successful second run the same guarded post-step runs on its own summary.json. The second
     output folder is the main output folder plus '_enum' (on Windows its path length is checked
     before the main run; with --skip-main only run_all.py checks it).

start.py itself deletes nothing and creates its own files only in exclusive mode (it never
overwrites a file). It writes below its own folder (.venv, outputs/_start) and into the output
folder, which --output-root can place elsewhere. The programs it starts are not covered by this
statement: pip replaces files inside .venv (for example when it upgrades pip), the editable
install may create src/ssn_hop_reconstruction.egg-info, and Python may write __pycache__ folders.

Exit codes:
    0, 2, 3, 4, 130  those of experiments/run_all.py, passed on unchanged
                     (2 is also used for a command-line error of this script, 130 for Ctrl+C)
    10               setup failure (venv or pip step failed, import probe failed, a file of
                     this script could not be written, a child process could not be started)
    11               no suitable Python found (needs 3.10 up to 3.14), or the re-start guard was set
                     (otherwise the exit code of the re-started child is passed on unchanged)
    12               problem with config.example.json or with the project layout
    13               the post-step (paper-style figures) failed; run_all.py itself had succeeded
    14               the second run (TBR_enumeration) failed after a successful main run
                     (with --skip-main the code of run_all.py is passed on unchanged);
                     if several apply, 14 wins over 13, and 13 over 0
Notes: a command-line error (argparse, --stages, a refused combination) and --help leave through SystemExit(2) / SystemExit(0); main() does not return then.
130 is returned when Ctrl+C was seen and the child ended with 0, or when the interrupt reached this script itself (setup steps, post-step). If the child ends
with another non-zero code after Ctrl+C (for example after it was killed on the third press) that code is passed on unchanged (main run, re-start, --skip-main second run).
A second run after a successful main run gives 14 for every code other than 0 and 130, also when it was interrupted; the code of run_all.py is printed in the message.
Any other code (for example 1 with a Python traceback) is an unexpected error of this script and is not described here.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# STAGES and ENUM_STAGES: stage names in pipeline order. MODEL_FILES: files that mark a finished training.
# RECIPE_SECTIONS: sections of config.json compared with the plan (model, data, train).
STAGES = ("plan", "train", "execute", "aggregate", "plot")
ENUM_STAGES = ("plan", "execute", "aggregate", "plot")
BASE_CONFIG_NAME = "config.example.json"
RUN_ALL_REL = "experiments/run_all.py"
PLOTS_REL = "experiments/paper_style_plots.py"
# The files whose bytes define the content-derived revision (content_revision). Patterns are relative to ROOT; a pattern that matches nothing is
# not an error (that file group is simply not part of the revision). Raw bytes are hashed, so a different line ending gives a different revision.
# Not covered: start.py, start_*.py, config.example.json, run.cmd, other files under experiments/, docs. The check that REQUIRED_FOR_REVISION
# exists (exit code 12) is made only when the revision is computed, not when --revision is given.
MANIFEST_PATTERNS = ("src/ssn_hops/*.py", "configs/*.json", "experiments/run_all.py",
                     "experiments/paper_style_plots.py")
REQUIRED_FOR_REVISION = (RUN_ALL_REL, "src/ssn_hops/__init__.py")
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")

DEFAULT_SUITE = "configs/suite_paper_scope.json"
QUICK_SUITE = "configs/suite_quick.json"
ENUM_SUITE = "configs/suite_tbr_enumeration.json"
ENUM_CALL_DEFAULT = 200000
ENUM_CELL_DEFAULT = 20000000
ASSUMED_RATE = 100000
ENUM_SUFFIX = "_enum"
RECIPE_SECTIONS = ("model", "data", "train")
MODEL_FILES = ("complete.json", "best.json", "best.pt", "config.json", "dataset_manifest.json",
               "provenance.json")

MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 15)
REEXEC_ENV = "SSN_START_REEXEC"
PY_PROBE_TIMEOUT_S = 30
PY_PROBE_CODE = "import sys; print(sys.executable); print(sys.version_info[0], sys.version_info[1])"

VENV_NAME = ".venv"
MARKER_NAME = "ssn_ready.json"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# Seconds: PROBE_TIMEOUT_S (import probe after pip), PY_PROBE_TIMEOUT_S (version probe of a candidate Python). pip, torch and the extras are installed
# WITHOUT version numbers, so a later setup can install other versions (the marker records what was found). The labels [2/4]..[4/4] are printed whenever
# pip runs; [1/4] only when the venv is created.
PIP_COMMON = ["--disable-pip-version-check", "--retries", "10", "--timeout", "60"]
PROBE_TIMEOUT_S = 900
# Units: characters of str(path). LONG_PATH_CHARS is the project path length from which only a warning is printed; no derivation is given in this file.
# The next two serve the length test of the check below (and its copy in run_all.py): on Windows a plan-folder path longer than 174 characters is refused
# unless long paths are confirmed enabled. 85 is the length reserved for the longest file path inside the plan folder; its origin is not derived here.
LONG_PATH_CHARS = 100
# The next two values are copies of the constants of experiments/run_all.py (preflight_output).
LONGEST_RELATIVE_PATH = 85
MAX_PATH_CHARS = 259
PROBE_MARK = "PROBE_JSON "
PROBE_CODE = (
    "import json, sys, numpy, torch, torch_geometric, matplotlib; "
    "from importlib import metadata as m; "
    "d = {str((x.metadata or {}).get('Name', '')).lower().replace('_', '-'): x.version "
    "for x in m.distributions()}; "
    "w = ['numpy', 'torch', 'torch-geometric', 'matplotlib', 'ssn-hop-reconstruction']; "
    "print('" + PROBE_MARK + "' + json.dumps({'python': sys.version.split()[0], "
    "'versions': {n: d.get(n, 'not-found') for n in w}}))")

# Fixed texts. The N range, epochs and p values agree with suite_paper_scope.json and suite_quick.json as they stood when the text was written; the 220 is not
# in either file, and no figure here is read from them; the hours are an estimate. Nothing changes the text for --models.
TIMING_NOTE = (
    "Full run, paper scope (220 cells, 5 trainings, CGR on every cell, N up to 396; with --models fewer\n"
    "trainings run and the time is shorter): expected duration 4.6 / 5.0 / 5.9 hours\n"
    "(optimistic / central / pessimistic).\n"
    "This is an ESTIMATE made from one earlier run of the old, smaller scope on one Windows computer,\n"
    "NOT a measurement of this scope; nothing can be resumed. For comparison only, that old run\n"
    "(measured once): total 2:30:20, of which training 1:39:57, cells 0:50:10, and plan, aggregate and\n"
    "plot together about 12 s.")
QUICK_NOTE = (
    "SMOKE TEST, the numbers are not results. Suite " + QUICK_SUITE + ": 3 training epochs,\n"
    "N = 132 only, p in {0, 0.04}. Its duration has NOT been measured.")

EXIT_USAGE = 2
EXIT_SETUP = 10
EXIT_NO_PYTHON = 11
EXIT_BASE_CONFIG = 12
EXIT_POSTSTEP = 13
EXIT_SECOND = 14
EXIT_INTERRUPTED = 130


class StartError(Exception):
    """A problem that ends the script with its own exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def say(text=""):
    """Print one line and flush."""
    print(text, flush=True)


# Only the streams of this process get errors="replace"; the console children (pip, run_all.py, the post-step) are untouched, while the two probes set PYTHONUTF8/PYTHONIOENCODING and decode the output with errors="replace".
def configure_streams():
    """Make the output tolerant of any console code page (non-encodable characters become ?)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


# The version text (also '3.10-3.14') appears in the module docstring, python_hint, restart_with_other_python and find_python, while the test uses MIN_PYTHON and
# MAX_PYTHON_EXCLUSIVE; change all the places together. The module docstring promise about an old Python 3 names no oldest version.
def python_ok():
    """True when this interpreter is 3.10 up to 3.14."""
    return MIN_PYTHON <= sys.version_info[:2] < MAX_PYTHON_EXCLUSIVE


def python_hint():
    """Text shown when no suitable Python is found."""
    return (
        "No suitable Python: this is Python %d.%d.%d, but 3.10 up to 3.14 is needed.\n"
        "Install Python from https://www.python.org/downloads/ (the only version the project "
        "authors know to have been used in a run is 3.14; the others are not verified).\n"
        "In the installer tick 'Add python.exe to PATH' and keep the 'py launcher' option, "
        "then open a NEW terminal window and start again. In VS Code: Ctrl+Shift+P, Python: "
        "Select Interpreter, pick a Python 3.10-3.14, press Run again. Or run run.cmd if it is present."
        % (sys.version_info[0], sys.version_info[1], sys.version_info[2]))


# ---------------------------------------------------------------- command line

def revision_arg(text):
    """argparse type: a 40-character lowercase hexadecimal string."""
    if not REVISION_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError("must be exactly 40 lowercase hexadecimal characters")
    return text


def budget_arg(text):
    """argparse type: a positive decimal integer (digits only)."""
    if not re.fullmatch(r"[0-9]+", text) or int(text) <= 0:
        raise argparse.ArgumentTypeError("must be a positive decimal integer")
    return int(text)


def build_parser():
    """The options of this script (unknown options are an error, nothing is passed through)."""
    parser = argparse.ArgumentParser(
        prog="start.py", allow_abbrev=False,
        description="One-command start: first-time setup, then experiments/run_all.py.",
        epilog="Exit codes: 0, 2, 3, 4, 130 as in run_all.py; 10 setup failure; "
               "11 no suitable Python; 12 base config or project layout problem; "
               "13 post-step (paper-style figures) failed; 14 second run failed after a "
               "successful main run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="run_all.py only checks and prints its commands; nothing heavy starts "
                             "(the first-time setup is still done when needed)")
    parser.add_argument("--stages", default=None,
                        help="comma list of stages to run, subset of: " + ", ".join(STAGES))
    parser.add_argument("--output-root", default=None,
                        help="output folder (a relative path is relative to the PROJECT FOLDER when "
                             "started through run.cmd, which changes into it first, and relative to "
                             "the current directory when start.py is called directly from another "
                             "folder); default: outputs/run_<YYYYMMDD_HHMMSS> in the project folder "
                             "(outputs/quick_<stamp> with --quick, outputs/tbr_enum_<stamp> with "
                             "--skip-main)")
    parser.add_argument("--revision", type=revision_arg, default=None,
                        help="use this 40-hex string (for example a git commit SHA) instead of "
                             "the content-derived one")
    parser.add_argument("--setup-only", action="store_true",
                        help="stop after the setup (nothing else is written)")
    parser.add_argument("--no-setup", action="store_true",
                        help="skip the setup and the import probe")
    parser.add_argument("--quiet", action="store_true",
                        help="do not pass --debug to run_all.py (no run_all.log file)")
    parser.add_argument("--quick", action="store_true",
                        help="SMOKE TEST with " + QUICK_SUITE + " (output outputs/quick_<stamp>); "
                             "the numbers are not results; its duration is not measured")
    parser.add_argument("--tbr-enumeration", action="store_true",
                        help="after a successful main run, a SECOND run with the optional policy "
                             "TBR_enumeration (suite " + ENUM_SUITE + ", output <main output>" + ENUM_SUFFIX + ")")
    parser.add_argument("--skip-main", action="store_true",
                        help="only valid with --tbr-enumeration: do not run the main run, run only "
                             "the second run (output outputs/tbr_enum_<stamp>)")
    parser.add_argument("--enum-call-budget", type=budget_arg, default=None, metavar="N",
                        help="only with --tbr-enumeration: safety budget of expansions per policy "
                             "call (default %d)" % ENUM_CALL_DEFAULT)
    parser.add_argument("--enum-cell-budget", type=budget_arg, default=None, metavar="N",
                        help="only with --tbr-enumeration: safety budget of expansions per cell "
                             "(default %d; SMALLER than the library default 200000000 on purpose)"
                             % ENUM_CELL_DEFAULT)
    parser.add_argument("--models", default=None, metavar="FOLDER",
                        help="reuse already trained models: the OUTPUT FOLDER of an earlier run (it "
                             "holds training/n<N>/run); sizes that are not found there are trained")
    return parser


def parse_stages(text, parser):
    """Validate --stages and return the names in the fixed pipeline order."""
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        parser.error("--stages needs at least one stage name: " + ", ".join(STAGES))
    for name in names:
        if name not in STAGES:
            parser.error("--stages: unknown stage %s; allowed: %s" % (ascii(name), ", ".join(STAGES)))
    if len(set(names)) != len(names):
        parser.error("--stages lists a stage twice")
    return [stage for stage in STAGES if stage in names]


def check_combinations(args, parser):
    """Refuse option combinations that would silently do nothing (exit code 2)."""
    if args.setup_only and args.no_setup:
        parser.error("--setup-only and --no-setup exclude each other")
    if args.skip_main and not args.tbr_enumeration:
        parser.error("--skip-main is only valid together with --tbr-enumeration")
    if not args.tbr_enumeration and (args.enum_call_budget is not None
                                     or args.enum_cell_budget is not None):
        parser.error("--enum-call-budget and --enum-cell-budget are only valid together with "
                     "--tbr-enumeration")
    if args.tbr_enumeration and args.stages is not None:
        parser.error("--stages selects stages of the MAIN run only; with --tbr-enumeration the second "
                     "run always runs plan, execute, aggregate and plot. Run the steps separately "
                     "(--tbr-enumeration --skip-main starts only the second run).")
    if args.skip_main and (args.quick or args.models is not None):
        parser.error("--skip-main means there is no main run, so --quick and --models do not apply")
    if args.quick and args.models is not None:
        parser.error("--models is for the full run (a quick run has N = 132 only); do not combine it "
                     "with --quick")


# ---------------------------------------------------------------- revision and config

def collect_manifest():
    """Sorted list of (posix relative path, Path) of the files that define the revision."""
    found = {}
    for pattern in MANIFEST_PATTERNS:
        for path in ROOT.glob(pattern):
            if path.is_file():
                found[path.relative_to(ROOT).as_posix()] = path
    return [(rel, found[rel]) for rel in sorted(found)]


def content_revision():
    """Return (40-hex SHA-1 over '<path>\\0<sha256 of bytes>\\n' lines, number of files)."""
    manifest = collect_manifest()
    names = [rel for rel, _path in manifest]
    missing = [rel for rel in REQUIRED_FOR_REVISION if rel not in names]
    if missing:
        raise StartError(EXIT_BASE_CONFIG,
                         "project files are missing next to start.py: %s. Is this the root of the "
                         "unpacked project (the folder that contains src, experiments, configs)?"
                         % ", ".join(missing))
    digest = hashlib.sha1(usedforsecurity=False)
    for rel, path in manifest:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise StartError(EXIT_BASE_CONFIG, "cannot read %s: %s" % (rel, ascii(str(exc))))
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest(), len(manifest)


def read_base_config():
    """Read config.example.json (UTF-8, BOM tolerated) and return the dictionary."""
    path = ROOT / BASE_CONFIG_NAME
    if not path.is_file():
        raise StartError(EXIT_BASE_CONFIG, "base config not found: " + str(path))
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise StartError(EXIT_BASE_CONFIG, "cannot read %s as UTF-8: %s" % (path, ascii(str(exc))))
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise StartError(EXIT_BASE_CONFIG, "%s is not valid JSON: %s" % (path, ascii(str(exc))))
    if not isinstance(data, dict):
        raise StartError(EXIT_BASE_CONFIG, "%s must contain a JSON object at the top level" % path)
    return data


def choose_output_root(argument, stamp, prefix="run_"):
    """Absolute output folder: the default is outputs/<prefix><stamp>; --output-root is taken from cwd."""
    if argument is None:
        return ROOT / "outputs" / (prefix + stamp)
    if not argument.strip():
        raise StartError(EXIT_USAGE, "--output-root must not be empty")
    return Path(argument).resolve()


def make_config(base, revision, out_root, stages):
    """Copy of the base config with revision, output_root and (optionally) stages replaced."""
    config = dict(base)
    config["revision"] = revision
    config["output_root"] = str(out_root)
    if stages is not None:
        config["stages"] = list(stages)
    return config


def write_config(config, stamp, prefix="config"):
    """Write a dictionary as a NEW JSON file below outputs/_start (never overwrites)."""
    folder = ROOT / "outputs" / "_start"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StartError(EXIT_SETUP, "cannot create %s: %s" % (folder, ascii(str(exc))))
    text = json.dumps(config, indent=2) + "\n"
    for number in range(1, 100):
        name = "%s_%s.json" % (prefix, stamp) if number == 1 else "%s_%s_%d.json" % (prefix, stamp, number)
        path = folder / name
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            continue
        except OSError as exc:
            raise StartError(EXIT_SETUP, "cannot write %s: %s" % (path, ascii(str(exc))))
        return path
    raise StartError(EXIT_SETUP, "no free config file name below " + str(folder))


def suite_sizes(rel):
    """{N: planes} over all grids of a suite file, or None when it cannot be read (best effort)."""
    try:
        with (ROOT / rel).open(encoding="utf-8") as handle:
            suite = json.load(handle)
        sizes = {}
        for grid in suite["grids"]:
            for size in grid["sizes"]:
                sizes[int(size["n"])] = int(size["planes"])
        return sizes
    except (OSError, ValueError, KeyError, TypeError):
        return None


def merge_dicts(base, changes):
    """Stdlib twin of merge() in src/ssn_hops/experiments.py: nested dictionaries are merged, other values replaced."""
    result = copy.deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_recipe_base():
    """Return (core template merged with the training_overrides of DEFAULT_SUITE, template file name).

    The same two inputs and the same merge as resolve_suite() in src/ssn_hops/experiments.py uses for
    the plan (core_template read next to the suite file); stdlib only, nothing is imported from torch.
    """
    suite_path = ROOT / DEFAULT_SUITE
    try:
        with suite_path.open(encoding="utf-8") as handle:
            suite = json.load(handle)
        core_path = suite_path.parent / suite["core_template"]
        with core_path.open(encoding="utf-8") as handle:
            core = json.load(handle)
        overrides = suite["training_overrides"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StartError(EXIT_BASE_CONFIG,
                         "--models: cannot read the training recipe of the plan from %s and its core "
                         "template: %s" % (DEFAULT_SUITE, ascii(str(exc))))
    if not isinstance(core, dict) or not isinstance(overrides, dict):
        raise StartError(EXIT_BASE_CONFIG,
                         "--models: the core template and the training_overrides of %s must be JSON "
                         "objects" % DEFAULT_SUITE)
    return merge_dicts(core, overrides), core_path.name


def recipe_differences(expected, actual, path, found):
    """Append (field path, expected value, actual value) for every field of expected that differs in actual.

    Only the keys present in expected are compared (keys that the template leaves to the defaults of
    src/ssn_hops/config.py cannot be compared). True and 1 count as different.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            found.append((path, expected, actual))
            return
        for key in sorted(expected):
            if key not in actual:
                found.append((path + "." + key, expected[key], "<missing>"))
            else:
                recipe_differences(expected[key], actual[key], path + "." + key, found)
        return
    if expected != actual or isinstance(expected, bool) != isinstance(actual, bool):
        found.append((path, expected, actual))


def scan_models(text):
    """Find trained runs <folder>/training/n<N>/run of an earlier output folder (or <folder>/n<N>/run).

    Returns ({"N": absolute run path}, banner lines). Checks that the files exist, that orbit n /
    planes in config.json fit the folder name and the suite, and that the training recipe (sections
    model, data and train of config.json: network, seeds, epochs, ...) equals the one the plan would
    use for that N; a difference is REFUSED (exit code 2). Stdlib only, no torch. Hashes and weights
    are checked later by the stage execute.
    """
    if not text.strip():
        raise StartError(EXIT_USAGE, "--models must not be empty")
    folder = Path(text).resolve()
    if not folder.is_dir():
        raise StartError(EXIT_USAGE, "--models: not a folder: " + str(folder))
    base = folder / "training" if (folder / "training").is_dir() else folder
    try:
        children = sorted(base.iterdir())
    except OSError as exc:
        raise StartError(EXIT_USAGE, "--models: cannot read %s: %s" % (base, ascii(str(exc))))
    found = {}
    for child in children:
        match = re.fullmatch(r"n([0-9]+)", child.name)
        if match is not None and (child / "run").is_dir():
            found[str(int(match.group(1)))] = child / "run"
    if not found:
        raise StartError(EXIT_USAGE,
                         "--models: no folder n<N>/run found below %s (give the output folder of an "
                         "earlier run: it holds training/n<N>/run)" % base)
    sizes = suite_sizes(DEFAULT_SUITE)
    base_recipe, core_name = load_recipe_base()
    mapping = {}
    for key in sorted(found, key=int):
        run = found[key]
        missing = [name for name in MODEL_FILES if not (run / name).is_file()]
        if missing:
            raise StartError(EXIT_USAGE,
                             "--models: the run for N=%s (%s) lacks: %s. Only a finished training "
                             "can be reused." % (key, run, ", ".join(missing)))
        try:
            with (run / "config.json").open(encoding="utf-8") as handle:
                run_config = json.load(handle)
            orbit = run_config["orbit"]
            run_n, run_planes = int(orbit["n"]), int(orbit["planes"])
        except (OSError, ValueError, KeyError, TypeError):
            raise StartError(EXIT_USAGE, "--models: cannot read orbit n and planes from %s"
                             % (run / "config.json"))
        if run_n != int(key):
            raise StartError(EXIT_USAGE, "--models: %s says N=%d but the folder name says N=%s"
                             % (run / "config.json", run_n, key))
        if sizes is not None:
            if int(key) not in sizes:
                raise StartError(EXIT_USAGE,
                                 "--models: N=%s is not a size of %s (sizes: %s); the plan would "
                                 "refuse it" % (key, DEFAULT_SUITE, ", ".join(str(n) for n in sorted(sizes))))
            if sizes[int(key)] != run_planes:
                raise StartError(EXIT_USAGE,
                                 "--models: N=%s was trained with %d planes but the suite uses %d"
                                 % (key, run_planes, sizes[int(key)]))
        expected = merge_dicts(base_recipe, {"orbit": {"n": int(key), "planes": run_planes}})
        differences = []
        for section in RECIPE_SECTIONS:
            recipe_differences(expected.get(section, {}), run_config.get(section), section, differences)
        if differences:
            shown = "; ".join("%s: plan %s, run %s" % (field, json.dumps(want), json.dumps(have))
                              for field, want, have in differences[:6])
            raise StartError(EXIT_USAGE,
                             "--models: the training recipe of the run for N=%s (%s) differs from what the "
                             "plan would use (%s plus the training_overrides of %s). %d difference(s) in "
                             "the sections %s; first: %s. A model trained differently (for example a smoke "
                             "test with few epochs) must not enter the full results, and there is no option "
                             "to override this. Use a folder whose runs were trained with the full recipe; "
                             "this script never deletes, so move that run away yourself if the size should "
                             "be trained now. If it was the only run in the folder, start again without --models instead."
                             % (key, run, core_name, DEFAULT_SUITE, len(differences),
                                ", ".join(RECIPE_SECTIONS), shown))
        mapping[key] = str(run.resolve())
    lines = ["models         : reused from " + str(base)]
    for key in sorted(mapping, key=int):
        lines.append("  reuse N=%s: %s" % (key, mapping[key]))
    if sizes is not None:
        todo = [str(n) for n in sorted(sizes) if str(n) not in mapping]
        lines.append("  trained now : " + (", ".join("N=" + n for n in todo) if todo else "none"))
    lines.append("  checked here: the six checkpoint files exist; orbit n and planes fit the folder name and the suite;")
    lines.append("  the training recipe in config.json (sections %s) equals the plan's (%s plus the"
                 % (", ".join(RECIPE_SECTIONS), core_name))
    lines.append("  training_overrides of %s) for every key that either of them names; keys left to the"
                 % DEFAULT_SUITE)
    lines.append("  library defaults are not compared. A difference is REFUSED before anything starts.")
    lines.append("  NOT checked here: orbit fields other than n and planes, hashes, weights. The stage execute,")
    lines.append("  which runs after the stage train has finished, makes its own checks; this script does not")
    lines.append("  verify or describe them.")
    return mapping, lines


def count_enum_cells():
    """Number of TBR_enumeration cells of the second-run suite (one per scenario), or None."""
    try:
        with (ROOT / ENUM_SUITE).open(encoding="utf-8") as handle:
            suite = json.load(handle)
        points = set()
        for grid in suite["grids"]:
            for size in grid["sizes"]:
                for probability in grid["probabilities"]:
                    points.add((int(size["n"]), float(probability)))
        return len(points) * len(suite["seed_tuples"]) * len(suite["sensitivities"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- child processes

def run_child(command, cwd, env=None):
    """Run a child process on the inherited console. Return (exit code, interrupted flag).

    Ctrl+C is not forwarded by this script: the console delivers it to the child as well, and
    the child (pip, run_all.py) does its own shutdown. After three presses the child is killed.
    env=None means: inherit the environment of this process.
    """
    try:
        process = subprocess.Popen(command, cwd=str(cwd), env=env)
    except OSError as exc:
        raise StartError(EXIT_SETUP, "cannot start %s: %s" % (subprocess.list2cmdline(command), ascii(str(exc))))
    interrupted = False
    presses = 0
    while True:
        try:
            code = process.wait(timeout=1.0)
            break
        except subprocess.TimeoutExpired:
            continue
        except KeyboardInterrupt:
            interrupted = True
            presses += 1
            if presses == 1:
                say("Ctrl+C received: waiting for the child process to stop "
                    "(press Ctrl+C two more times to end it by force).")
            if presses >= 3:
                process.kill()
                try:
                    code = process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    code = -1
                break
    return code, interrupted


def venv_python():
    """Interpreter of the project virtual environment (the POSIX path is unverified)."""
    if os.name == "nt":
        return ROOT / VENV_NAME / "Scripts" / "python.exe"
    return ROOT / VENV_NAME / "bin" / "python"


def probe_python(command):
    """Run <command> -c PY_PROBE_CODE. Return (sys.executable text, (major, minor)) or None on any problem."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run(list(command) + ["-c", PY_PROBE_CODE], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8",
                              errors="replace", timeout=PY_PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    parts = lines[-1].split()
    try:
        version = (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None
    return lines[-2], version


def usable_python(probed):
    """The path of a probed interpreter when it may be used for the re-start, else None.

    Refused: a version outside 3.10 up to 3.14, a path under WindowsApps (Microsoft Store), a path
    that is not an existing file, and this very interpreter.
    """
    if probed is None:
        return None
    path, version = probed
    if not MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE:
        return None
    if "windowsapps" in path.lower():
        return None
    if not os.path.isfile(path):
        return None
    try:
        if os.path.samefile(path, sys.executable):
            return None
    except OSError:
        pass
    return path


def find_python():
    """Path of another suitable interpreter, or None.

    Order: the project venv python (when the marker file exists); on Windows 'py -3.14' down to
    'py -3.10'; on POSIX python3.14 down to python3.10 found on PATH. Bare 'python' is never tried.
    """
    candidates = []
    venv = venv_python()
    if venv.is_file() and (ROOT / VENV_NAME / MARKER_NAME).is_file():
        candidates.append([str(venv)])
    for minor in range(MAX_PYTHON_EXCLUSIVE[1] - 1, MIN_PYTHON[1] - 1, -1):
        if os.name == "nt":
            candidates.append(["py", "-3.%d" % minor])
        else:
            located = shutil.which("python3.%d" % minor)
            if located is not None:
                candidates.append([located])
    for command in candidates:
        path = usable_python(probe_python(command))
        if path is not None:
            return path
    return None


def restart_with_other_python(args_list):
    """python_ok() is false: start start.py again with another interpreter; return the child's exit code.

    EXIT_NO_PYTHON is only the final fallback (the guard variable is set, or nothing suitable was found).
    The child inherits stdout, stderr and the working directory; its exit code is passed on unchanged.
    """
    if os.environ.get(REEXEC_ENV):
        say("ERROR (exit code %d): start.py was already re-started once (%s is set) and this is still "
            "Python %d.%d, so it does not start itself again.\n%s"
            % (EXIT_NO_PYTHON, REEXEC_ENV, sys.version_info[0], sys.version_info[1], python_hint()))
        return EXIT_NO_PYTHON
    target = find_python()
    if target is None:
        say("ERROR (exit code %d): %s" % (EXIT_NO_PYTHON, python_hint()))
        return EXIT_NO_PYTHON
    say("This is Python %d.%d; 3.10-3.14 is needed. Re-starting start.py with %s."
        % (sys.version_info[0], sys.version_info[1], target))
    env = dict(os.environ)
    env[REEXEC_ENV] = "1"
    command = [target, str(ROOT / "start.py")] + list(args_list)
    try:
        code, interrupted = run_child(command, Path.cwd(), env)
    except (OSError, StartError) as exc:
        say("ERROR (exit code %d): cannot re-start start.py with %s: %s" % (EXIT_SETUP, target, ascii(str(exc))))
        return EXIT_SETUP
    if interrupted and code == 0:
        code = EXIT_INTERRUPTED
    return code


def synced_folder(path):
    """Same logic as synced_folder() in experiments/run_all.py: OneDrive or Dropbox in the path."""
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith("onedrive") or lowered.startswith("dropbox"):
            return True
    for key, value in os.environ.items():
        if key.upper().startswith("ONEDRIVE") and value:
            try:
                path.relative_to(Path(value))
            except ValueError:
                continue
            return True
    return False


def warn_if_risky_path():
    """Print a WARNING (never an error, never a stop) before the first venv or pip step."""
    reasons = []
    if len(str(ROOT)) > LONG_PATH_CHARS:
        reasons.append("the project path has %d characters (more than %d)"
                       % (len(str(ROOT)), LONG_PATH_CHARS))
    if synced_folder(ROOT):
        reasons.append("the path looks like a cloud-synchronised folder (OneDrive or Dropbox)")
    if reasons:
        say("WARNING: " + "; ".join(reasons) + ". A long or synchronised path may make the "
            "setup fail deep in the torch installation (hypothesis, not tested). Safer: move the "
            "project to a short path such as C:\\cw2 and run again. The run continues now.")


def long_paths_enabled():
    """Same as long_paths_enabled() in experiments/run_all.py: True/False from the registry; None when unknown."""
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


def second_root_of(args, out_root):
    """Output folder of the second run: the main one plus ENUM_SUFFIX, or the main one itself with --skip-main."""
    return out_root if args.skip_main else Path(str(out_root) + ENUM_SUFFIX)


def check_second_root_length(second_root):
    """The path-length test of run_all.preflight_output, applied to the SECOND root before the main run starts.

    run_all.py refuses (exit code 3) when len(str(plan folder)) + 85 > 259 on Windows and long paths are
    not confirmed enabled; the plan folder is <output root>/plan. Here the same test gives exit code 2.
    """
    if os.name != "nt":
        return
    length = len(str(second_root / "plan"))
    if length + LONGEST_RELATIVE_PATH > MAX_PATH_CHARS and long_paths_enabled() is not True:
        raise StartError(
            EXIT_USAGE,
            "the output folder of the SECOND run would be %s (%d characters; the main folder plus '%s'). Its "
            "plan folder path has %d characters, the longest planned file adds about %d, which exceeds the %d "
            "characters of the classic Windows path limit, and long paths are not confirmed enabled (the same "
            "test as experiments/run_all.py). If the main output folder is already too long, run_all.py "
            "refuses the main run at its pre-flight (exit code 3); otherwise the main run would pass and "
            "only the second run would be refused, after hours. Nothing was started. Use a shorter "
            "--output-root or a shorter project path (for "
            "example C:\\cw2)."
            % (second_root, len(str(second_root)), ENUM_SUFFIX, length, LONGEST_RELATIVE_PATH, MAX_PATH_CHARS))


def run_setup_step(label, command):
    """Run one setup command; any failure ends the script with exit code 10."""
    say("[setup] " + label)
    say("[setup] command: " + subprocess.list2cmdline(command))
    code, interrupted = run_child(command, ROOT)
    if interrupted:
        raise KeyboardInterrupt()
    if code != 0:
        raise StartError(
            EXIT_SETUP,
            "the setup step '%s' ended with exit code %d. Read the output above. A network "
            "interruption is a possible cause, or a path that is too long (move the project to "
            "a short path such as C:\\cw2) (hypotheses, not established by this script). "
            "Nothing was deleted. After a failed pip step run the same command again (pip is "
            "expected to reuse what it downloaded). After a failed creation of the virtual "
            "environment check that its python exists; if not, delete the .venv folder yourself "
            "first." % (label, code))


def import_probe(py):
    """Import numpy, torch, torch_geometric, matplotlib in the venv. Return (info or None, problem)."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        done = subprocess.run([str(py), "-c", PROBE_CODE], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                              errors="replace", timeout=PROBE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None, "the import probe did not finish within %d seconds" % PROBE_TIMEOUT_S
    except OSError as exc:
        return None, "the venv python could not be started: " + ascii(str(exc))
    lines = done.stdout.splitlines()
    info = None
    for line in lines:
        if line.startswith(PROBE_MARK):
            try:
                info = json.loads(line[len(PROBE_MARK):])
            except ValueError:
                info = None
    if done.returncode != 0 or not isinstance(info, dict):
        return None, "exit code %d; last output lines:\n%s" % (done.returncode, "\n".join(lines[-25:]))
    return info, ""


def write_marker(info):
    """Write .venv/ssn_ready.json once (never overwrites an existing marker)."""
    marker = ROOT / VENV_NAME / MARKER_NAME
    body = {"format": 1, "written_by": "start.py", "python": info.get("python"),
            "versions": info.get("versions"),
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds")}
    try:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(body, indent=2) + "\n")
    except FileExistsError:
        return
    except OSError as exc:
        raise StartError(EXIT_SETUP, "cannot write the marker %s: %s" % (marker, ascii(str(exc))))


def ensure_setup():
    """Create .venv and install what is needed (first run) or probe the existing one. Return its python."""
    venv_dir = ROOT / VENV_NAME
    py = venv_python()
    marker = venv_dir / MARKER_NAME
    if not py.is_file() or not marker.is_file():
        warn_if_risky_path()
    if not py.is_file():
        if venv_dir.exists():
            raise StartError(EXIT_SETUP,
                             "the folder %s exists but %s is missing, so it is not a usable "
                             "environment. This script never deletes anything: delete the %s "
                             "folder yourself and run again." % (venv_dir, py, VENV_NAME))
        run_setup_step("[1/4] create the virtual environment %s" % VENV_NAME,
                       [sys.executable, "-m", "venv", str(venv_dir)])
        if not py.is_file():
            raise StartError(EXIT_SETUP, "the venv was created but %s does not exist" % py)
    if marker.is_file():
        say("[setup] marker found: " + str(marker))
        info, problem = import_probe(py)
        if info is None:
            raise StartError(EXIT_SETUP,
                             "the environment is marked ready but the import probe failed: %s\n"
                             "The environment is damaged or was moved. This script never deletes "
                             "anything: delete the %s folder yourself and run again."
                             % (problem, VENV_NAME))
        say("[setup] import probe passed (numpy, torch, torch_geometric, matplotlib).")
        return py
    base = [str(py), "-m", "pip"]
    run_setup_step("[2/4] update pip", base + ["install", "--upgrade", "pip"] + PIP_COMMON)
    run_setup_step("[3/4] install torch, CPU build (large download; the first run needs internet)",
                   base + ["install", "torch", "--index-url", TORCH_CPU_INDEX] + PIP_COMMON)
    run_setup_step("[4/4] install the project with the plot extra (pulls numpy and torch-geometric)",
                   base + ["install", "-e", ".[plot]"] + PIP_COMMON)
    say("[setup] running the import probe (the first import of torch can take a while)")
    info, problem = import_probe(py)
    if info is None:
        raise StartError(EXIT_SETUP,
                         "the installation finished but the import probe failed: %s\n"
                         "No marker was written. Run again to repeat the pip steps, or delete the "
                         "%s folder yourself (this script never deletes) and run again."
                         % (problem, VENV_NAME))
    write_marker(info)
    say("[setup] import probe passed; marker written: " + str(marker))
    say("[setup] versions: " + json.dumps(info.get("versions")))
    return py


# ---------------------------------------------------------------- main flow

def print_banner(args, stages, out_root, revision, origin, config_path, py, suite, models_lines):
    """Facts shown before the long part."""
    say("")
    say("=== ssn_hops one-command start ===")
    say("project folder : " + str(ROOT))
    say("python         : " + str(py))
    say("suite          : " + suite)
    say("stages         : " + ", ".join(stages))
    say("output folder  : " + str(out_root))
    say("revision (%s): %s" % (origin, revision))
    say("config file    : " + str(config_path))
    if models_lines is not None:
        for line in models_lines:
            say(line)
    if args.dry_run:
        say("--dry-run: nothing heavy is started; run_all.py only checks and prints its commands.")
    else:
        if args.quick:
            say(QUICK_NOTE)
        else:
            say(TIMING_NOTE)
            if len(stages) < len(STAGES):
                say("(that figure is for the full pipeline; you selected a subset of the stages)")
        say("The stages train and execute print little for a long time; that is expected "
            "(a [heartbeat] line appears about once a minute).")
        say("Ctrl+C stops the run; an interrupted run cannot be resumed (start again: new folder).")
    if args.tbr_enumeration and not args.skip_main:
        say("After a successful main run a SECOND run follows (TBR_enumeration, " + ENUM_SUITE + ").")
    say("")


def print_enum_banner(second_root, revision, config_path, call_budget, cell_budget):
    """Facts and the worst-case warning before the TBR_enumeration run."""
    cells = count_enum_cells()
    worst = float(cell_budget + call_budget) / ASSUMED_RATE
    say("")
    say("=== TBR_enumeration second run (optional policy; not the default) ===")
    say("suite          : " + ENUM_SUITE + " (baselines only: TSR, TBR(BFS) and TBR_enumeration; no GLR, no CGR)")
    say("stages         : " + ", ".join(ENUM_STAGES) + " (train is not needed: no GLR)")
    say("output folder  : " + str(second_root))
    say("revision       : " + revision + " (the value a main run of this invocation would use)")
    say("config file    : " + str(config_path))
    say("budgets        : %d expansions per call, %d expansions per cell "
        "(library default per cell: 200000000; this script uses a smaller one on purpose)"
        % (call_budget, cell_budget))
    say("WORST CASE per cell: (cell budget %d + call budget %d, because a cell can exceed its budget by up to "
        "one call) / %d per second = %.0f s (about %.1f min). The rate of %d expansions per second is "
        "ASSUMED, not measured; the simulator time is not included."
        % (cell_budget, call_budget, ASSUMED_RATE, worst, worst / 60.0, ASSUMED_RATE))
    if cells is not None:
        say("Cells with TBR_enumeration in this suite: %d, so at most %.1f min for them at the assumed rate "
            "(the time of the other policies is not included)." % (cells, cells * worst / 60.0))
    say("At one fifth of the assumed rate the worst case is five times longer. Measure first: after this run "
        "compute the seconds per expansion from its cell results (pooled route seconds of TBR_enumeration "
        "divided by its total expansions; in summary.json: groups[*].policies.TBR_enumeration."
        "pooled_packet_and_call.route_seconds and groups[*].enumeration_completeness.total_expansions) "
        "BEFORE you raise --enum-call-budget or --enum-cell-budget.")
    say("A search that hits a budget is INCOMPLETE: the packet waits (no route from partial work, no fallback), "
        "so the delivery numbers of this policy reflect the budget. Read enumeration_completeness first.")
    say("")


def print_where(out_root, stages, quiet):
    """After a successful full run: where the results are (existence is checked now)."""
    items = []
    if "plan" in stages:
        items.append(("plan folder", out_root / "plan"))
    if "aggregate" in stages:
        items.append(("summary.json", out_root / "summary.json"))
    if "plot" in stages:
        items.append(("plots folder", out_root / "plots"))
    if not quiet:
        items.append(("run_all.log", out_root / "run_all.log"))
    say("")
    say("Where to look:")
    for label, path in items:
        say("  %-13s %s  [%s]" % (label, path, "found" if path.exists() else "NOT found"))


def launch_run_all(py, config_path, args):
    """One run_all.py call on the generated config; prints its exit code line and returns the code."""
    command = [str(py), str(ROOT / "experiments" / "run_all.py"), "--config", str(config_path)]
    if not args.quiet:
        command.append("--debug")
    if args.dry_run:
        command.append("--dry-run")
    say("command: " + subprocess.list2cmdline(command))
    code, interrupted = run_child(command, ROOT)
    if interrupted and code == 0:
        code = EXIT_INTERRUPTED
    say("")
    say("run_all.py exit code: %d (0 ok, 2 config or usage error, 3 pre-flight failure, "
        "4 a stage failed, 130 interrupted)" % code)
    return code


def report_exit(code, args, out_root, stages, smoke):
    """Messages after one run_all.py call."""
    if code == 0 and args.dry_run:
        say("Dry run finished: nothing heavy was started. For the real run: run.cmd (the same options "
            "without --dry-run)")
    elif code == 0:
        say("All requested stages ended with exit code 0. This says nothing about the scientific "
            "validity of the results.")
        if smoke:
            say("SMOKE TEST: the numbers of this run are not results.")
        print_where(out_root, stages, args.quiet)
    elif code == 3:
        say("Pre-flight problem: nothing was started. Read the PRE-FLIGHT PROBLEM lines above.")
    elif code != EXIT_INTERRUPTED:
        say("Send the full output of this window and, if it exists, the file run_all.log in the output "
            "folder (there is none with --quiet; see START_HERE_RU.md).")


def run_poststep(py, out_root):
    """Paper-style figures: experiments/paper_style_plots.py --summary <out>/summary.json --out <out>/paper_style.

    Returns 0 (done, or skipped with a notice), EXIT_POSTSTEP (failed) or EXIT_INTERRUPTED.
    A failure here never changes or hides the result of run_all.py printed before.
    """
    script = ROOT / "experiments" / "paper_style_plots.py"
    summary = out_root / "summary.json"
    target = out_root / "paper_style"
    say("")
    if not script.is_file():
        say("[post-step] %s not found: the paper-style figures are skipped (not an error)." % PLOTS_REL)
        return 0
    if not summary.is_file():
        say("[post-step] %s not found: the paper-style figures are skipped." % summary)
        return 0
    command = [str(py), str(script), "--summary", str(summary), "--out", str(target)]
    say("[post-step] paper-style figures (the result of run_all.py above is not affected by this step)")
    say("[post-step] command: " + subprocess.list2cmdline(command))
    try:
        code, interrupted = run_child(command, ROOT)
    except StartError as exc:
        say("[post-step] FAILED: " + exc.message)
        return EXIT_POSTSTEP
    if interrupted:
        say("[post-step] interrupted by Ctrl+C.")
        return EXIT_INTERRUPTED
    if code != 0:
        say("[post-step] FAILED with exit code %d (start.py exit code %d unless a later step ends "
            "differently). summary.json and the plots of run_all.py are not affected. Send the output "
            "of this window." % (code, EXIT_POSTSTEP))
        return EXIT_POSTSTEP
    say("[post-step] exit code 0; folder %s [%s]" % (target, "found" if target.exists() else "NOT found"))
    return 0


def run_main(args, base, revision, origin, py, out_root, stamp, effective, shown_stages, models_map,
             models_lines):
    """The main run_all.py call (paper scope, or --quick) and the post-step. Returns (code, post-step code)."""
    suite = QUICK_SUITE if args.quick else DEFAULT_SUITE
    config = make_config(base, revision, out_root, effective)
    config["suite"] = suite
    if models_map is not None:
        plan = base.get("plan")
        if not isinstance(plan, dict):
            raise StartError(EXIT_BASE_CONFIG, "'plan' in %s must be a mapping" % BASE_CONFIG_NAME)
        plan = dict(plan)
        plan["models"] = str(write_config(models_map, stamp, "models"))
        config["plan"] = plan
    config_path = write_config(config, stamp)
    print_banner(args, shown_stages, out_root, revision, origin, config_path, py, suite, models_lines)
    code = launch_run_all(py, config_path, args)
    report_exit(code, args, out_root, shown_stages, args.quick)
    post = 0
    if code == 0 and not args.dry_run and not args.quick and "aggregate" in shown_stages:
        post = run_poststep(py, out_root)
    return code, post


def run_second(args, base, revision, py, out_root, stamp):
    """The TBR_enumeration run: a SEPARATE run_all.py call with its own generated config.

    Returns (its exit code, post-step code); the post-step runs only after a successful second run.
    """
    call_budget = ENUM_CALL_DEFAULT if args.enum_call_budget is None else args.enum_call_budget
    cell_budget = ENUM_CELL_DEFAULT if args.enum_cell_budget is None else args.enum_cell_budget
    second_root = second_root_of(args, out_root)
    config = make_config(base, revision, second_root, list(ENUM_STAGES))
    config["suite"] = ENUM_SUITE
    config["plan"] = {"models": None, "baselines_only": True, "include_native_tbr": False,
                      "tbr_max_nodes": None, "tbr_max_expansions": None,
                      "include_tbr_enumeration": True,
                      "enum_max_call_expansions": call_budget,
                      "enum_max_cell_expansions": cell_budget}
    config["aggregate"] = {"allow_partial": False, "reference": "TBR_style_hop_oracle"}
    config["plot"] = {"allow_partial": False}
    config_path = write_config(config, stamp, "config_tbr_enum")
    print_enum_banner(second_root, revision, config_path, call_budget, cell_budget)
    code = launch_run_all(py, config_path, args)
    report_exit(code, args, second_root, list(ENUM_STAGES), False)
    post = 0
    if code == 0 and not args.dry_run:
        say("")
        say("[post-step] second run (TBR_enumeration): paper-style figures from the summary.json of " + str(second_root))
        post = run_poststep(py, second_root)
    return code, post


def run_start(args, stages):
    """Whole run; returns the exit code or raises StartError / KeyboardInterrupt."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.revision is not None:
        revision = args.revision
        origin = "supplied with --revision"
        say("revision manifest: not used (--revision given)")
    else:
        revision, count = content_revision()
        origin = "content-derived, NOT a git commit"
        say("revision manifest: %d files (%s)" % (count, ", ".join(MANIFEST_PATTERNS)))
    base = read_base_config()
    if args.skip_main:
        prefix = "tbr_enum_"
    elif args.quick:
        prefix = "quick_"
    else:
        prefix = "run_"
    out_root = choose_output_root(args.output_root, stamp, prefix)
    effective = list(stages) if stages is not None else None
    shown_stages = effective if effective is not None else base.get("stages", list(STAGES))
    if not isinstance(shown_stages, list):
        raise StartError(EXIT_BASE_CONFIG, "'stages' in %s must be a list" % BASE_CONFIG_NAME)
    models_map = None
    models_lines = None
    if args.models is not None:
        models_map, models_lines = scan_models(args.models)
    if args.tbr_enumeration and not args.skip_main:
        check_second_root_length(second_root_of(args, out_root))

    if args.no_setup:
        py = venv_python()
        if not py.is_file():
            say("[setup] --no-setup: %s not found, using the current Python: %s" % (py, sys.executable))
            py = Path(sys.executable)
        else:
            say("[setup] --no-setup: setup and import probe skipped.")
    else:
        py = ensure_setup()
    if args.setup_only:
        say("")
        say("Setup finished (--setup-only). Nothing else was done. Start the pipeline with run.cmd.")
        return 0

    post = 0
    if args.skip_main:
        say("Main run skipped (--skip-main): only the TBR_enumeration run follows.")
    else:
        code, post = run_main(args, base, revision, origin, py, out_root, stamp, effective, shown_stages,
                              models_map, models_lines)
        if code != 0:
            if args.tbr_enumeration:
                say("")
                say("The TBR_enumeration run was NOT started: the main run did not end with exit code 0.")
            return code
        if post == EXIT_INTERRUPTED:
            return post
    if not args.tbr_enumeration:
        return post
    second, second_post = run_second(args, base, revision, py, out_root, stamp)
    if second == 0:
        if second_post == EXIT_INTERRUPTED:
            return second_post
        return post if post != 0 else second_post
    if args.skip_main or second == EXIT_INTERRUPTED:
        return second
    say("")
    say("ERROR (exit code %d): the main run succeeded, but the TBR_enumeration run ended with run_all.py "
        "exit code %d. The results of the main run are not affected." % (EXIT_SECOND, second))
    return EXIT_SECOND


def main(argv=None):
    """Entry point; returns the process exit code."""
    configure_streams()
    if not python_ok():
        try:
            return restart_with_other_python(list(sys.argv[1:] if argv is None else argv))
        except KeyboardInterrupt:
            say("")
            say("Interrupted by Ctrl+C while looking for another Python. Nothing was deleted.")
            return EXIT_INTERRUPTED
    parser = build_parser()
    args = parser.parse_args(argv)
    stages = parse_stages(args.stages, parser) if args.stages is not None else None
    check_combinations(args, parser)
    try:
        return run_start(args, stages)
    except StartError as exc:
        say("")
        say("ERROR (exit code %d): %s" % (exc.code, exc.message))
        return exc.code
    except KeyboardInterrupt:
        say("")
        say("Interrupted by Ctrl+C. Nothing was deleted. Setup steps are repeatable: run again. If the "
            ".venv folder was just being created and the python inside it is missing, delete .venv "
            "yourself first (this script never deletes).")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
