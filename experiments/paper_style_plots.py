"""Paper-style figures for ssn_hops experiment summaries (revision 5, T129).

Runtime status: NOT executed by its author (static reading only). The first run by the user
is the first test. Python 3.10+, standard library + matplotlib (Agg backend only).

Usage (from the project folder):
    python experiments/paper_style_plots.py --summary <run>/summary.json --out <run>/paper_style
    python experiments/paper_style_plots.py --style-demo <folder>
    (both can be combined; --allow-partial is optional and labels the figures PARTIAL)

--out and --style-demo folders must not exist or must be empty: nothing is overwritten.
The existing six plots of experiment_plots.py are not touched. This script only READS a
summary.json; no number of the paper is ever drawn in a figure that shows our data. The
numbers of the paper appear ONLY in the separate figure of --style-demo.

Validation and curve data come from ssn_hops.experiment_plots.prepare_plot_data(summary,
summary_sha256=None, allow_partial=False). If that module cannot be imported (also after the
project's src folder is put on sys.path) the script prints one ERROR line, writes nothing and
exits with 3; it never falls back to unvalidated data.

Figures (each as <name>.png without error bars = paper style, and <name>_se.png with SE bars):
    fig3a_delay_vs_p, fig3b_loss_vs_p, fig4_delay_vs_N (grouped bars), fig4_loss_vs_N (extra),
    fig5_cost_vs_N, fig5_cost_vs_N_logy. A figure whose data are absent is skipped and reported
    by name; a missing point is absent (never a zero bar).

Exit codes: 0 done (skipped figures are listed), 1 no figure could be drawn, 2 usage or
output-folder problem, 3 summary refused or ssn_hops not importable, 4 matplotlib missing or
a figure failed while drawing.
"""
import argparse
import json
import math
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Exit codes of main() and the conditions under which it returns them (the module docstring gives a shorter statement).
# 0 EXIT_OK: at least one file was written and none failed; skipped figures are listed as 'SKIPPED figure ...' lines.
# 1 EXIT_NOFIG: nothing was written and nothing failed (for example every figure was skipped; the --out folder is then not created).
# 2 EXIT_USAGE: an output-folder problem found by main (printed as 'ERROR: ...'); option errors are reported by parse_args.
# 3 EXIT_INPUT: ssn_hops cannot be imported, or the summary is refused; both print 'Nothing was written.' A --style-demo given in
#   the same command is not drawn then, because the summary step runs first and main returns at once.
# 4 EXIT_RENDER: matplotlib cannot be imported ('Nothing was written.'), or at least one file failed while drawing (the other
#   files are still written).
# main catches only ImportError around the matplotlib import, and only ValueError, KeyError, TypeError and AttributeError around
# reading and checking the summary; other exceptions are not handled in main.
# The line 'paper_style_plots: N file(s) written, M figure(s) skipped, K file(s) failed' is printed only before returning 0, 1 or 4
# (after failed files); the 'WROTE <path>' lines are printed after all drawing is finished.
EXIT_OK = 0
EXIT_NOFIG = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_RENDER = 4

ENUM_NAME = "TBR_enumeration"
ORDER = ("GLR", "TBR_style_hop_oracle", "CGR_contact_plan", "TSR_source_dijkstra", ENUM_NAME)
COST_KEYS = ("GLR", "TBR_style_hop_oracle", "CGR_contact_plan", ENUM_NAME)
# Legend labels. 'TBR' stands for the BFS hop oracle of this project (see NOTE_MAIN); the cost figures use COST_NAMES,
# which labels it 'TBR (BFS)'.
NAMES = {"GLR": "GLR", "TBR_style_hop_oracle": "TBR", "CGR_contact_plan": "CGR",
         "TSR_source_dijkstra": "TSR", ENUM_NAME: "TBR-enum"}
COST_NAMES = dict(NAMES, TBR_style_hop_oracle="TBR (BFS)")
# Colours and hatches of paper Fig. 4 by eye (T129 contract); marker per policy for line figures.
# The line above calls the whole table 'by eye'; that holds only in part. From the written by-eye description of the paper's Fig. 4:
# grouped bars; order GLR, TBR, CGR, TSR; black edges; fills light green (solid), light orange (hatch '/'), light purple (hatch
# 'backslash'), light blue (hatch 'x'); a framed legend inside the plot at the upper right, two columns by two rows; serif bold fonts;
# white background; light grey horizontal grid; ticks pointing inward. The description gives colour words, not hexadecimal values: the
# hexadecimal values below, GRID_COLOR, and the ticks on the top and right axes are this script's own choices. Not from the
# description at all: the TBR_enumeration entry (the description shows four series), every marker (markers are used only in the line
# figures; the description has bars only) and SHARE_COLOR. The styles of the paper's Figs. 3 and 5 are not known (see NOTE_STYLE);
# the figures that stand for them reuse this table.
STYLE = {
    "GLR": {"color": "#a8dba0", "hatch": "", "marker": "o"},
    "TBR_style_hop_oracle": {"color": "#fdc78d", "hatch": "/", "marker": "s"},
    "CGR_contact_plan": {"color": "#c3b1dc", "hatch": "\\", "marker": "^"},
    "TSR_source_dijkstra": {"color": "#92b4ee", "hatch": "x", "marker": "D"},
    ENUM_NAME: {"color": "#f3a7a7", "hatch": "o", "marker": "v"},
}
# SHARE_COLOR: colour of the percent labels (completeness share of TBR-enum). GRID_COLOR: colour of the horizontal grid lines.
SHARE_COLOR = "#a03030"
GRID_COLOR = "#d0d0d0"
# Matplotlib settings applied through rc_context in render(): serif bold fonts (the description says serif, Times-like, bold), white
# background, black axes edge, hatch line width 1.0. The font list and the hatch line width are this script's own choices.
RC = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.weight": "bold",
    "axes.labelweight": "bold",
    "axes.titleweight": "bold",
    "axes.edgecolor": "black",
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "hatch.linewidth": 1.0,
}

# Texts printed on the figures of this project's data: the title (TITLE_HEAD, ' / PARTIAL' when summary['complete'] is not True, then
# a subtitle), the axis labels, the legend labels (NAMES) and, at the bottom in grey, a block of notes in this order: NOTE_PARTIAL (if
# partial), NOTE_MAIN, the notes of the figure, NOTE_ENUM (if TBR-enum is drawn), the list of summary policies not drawn, the notes
# about absent data; the files ending in _se add SE_NOTE. TBR-enum points carry red percent labels (its completeness share).
# NOTE_P, NOTE_LOSS, NOTE_COST and NOTE_ENUM are fixed texts about this project's own quantities; this script neither computes nor
# checks what they say.
TITLE_HEAD = "Reconstruction, not the authors' results"
NOTE_MAIN = "Reconstruction, not the authors' results; TBR = BFS hop oracle, not the paper's brute force"
NOTE_ENUM = ("TBR-enum = full enumeration of this reconstruction with safety budgets, not the paper's brute "
             "force; an incomplete search makes the packet wait (no route is taken from partial work), so its "
             "values include those waits; percent labels = share of its search calls that completed")
NOTE_PARTIAL = "PARTIAL summary (--allow-partial): not every planned cell is verified"
NOTE_STYLE = "style of this figure in the paper unverified (colours and fonts of paper Fig. 4 reused)"
NOTE_DELAY = ("delay = mean delay of DELIVERED packets only (equal-replicate mean over matched repetitions); "
              "groups with different failure fractions are not equivalent on this metric")
NOTE_LOSS = ("loss = failed/generated times 100; our failure includes TTL expiry and retry exhaustion; "
             "the paper's loss definition is unknown")
NOTE_P = ("x = 100 * p; p is this reconstruction's per-active-transfer-tick abort probability; the meaning of "
          "the paper's interruption probability is unverified")
NOTE_COST = ("y = CPU wall seconds per route call of THIS implementation (including inference); the paper's "
             "unit is unknown")
NOTE_FIG4 = ("style model: paper Fig. 4 (grouped bars, colours, hatching, legend position, serif bold fonts); "
             "values of the paper are not shown in this figure")
SE_NOTE = "Error bars: one SE of the equal-replicate mean, not a confidence interval; a point with one observation has no bar."

# By-eye bar heights of paper Fig. 4 (PAPER_FIG4_DESCRIPTION.md, +-0.15 s). USED ONLY by --style-demo.
# Added to the line above: the numbers below are SECONDS, read by eye from the written by-eye description of the paper's Fig. 4
# (tolerance about +-0.15 s; that description is their only source). They are not data: not measured, and not produced by this script
# or by any experiment. DEMO_N are the five tick labels (network sizes) of that figure. The keys of DEMO_HEIGHTS are this project's
# policy names, used as stand-ins for the paper's bar labels GLR, TBR, CGR and TSR; the numbers under TBR_style_hop_oracle are the
# paper's TBR bars, not a result of this project's hop oracle. Used only by make_demo_job (option --style-demo).
DEMO_N = (132, 198, 264, 330, 396)
DEMO_HEIGHTS = {
    "GLR": (7.05, 6.8, 6.6, 6.4, 6.4),
    "TBR_style_hop_oracle": (7.75, 7.3, 7.2, 6.65, 6.55),
    "CGR_contact_plan": (10.75, 10.35, 10.3, 10.3, 10.15),
    "TSR_source_dijkstra": (13.35, 12.5, 12.05, 11.85, 11.35),
}
DEMO_BANNER = "STYLE DEMO: bar heights read by eye from the paper (+-0.15 s); NOT our results"


# ----------------------------------------------------------------------------- small helpers

def _num(value):
    """Finite number as float, else None (bool is not a number here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def fmt_x(value):
    """Short text of an x value (N or percent)."""
    return "%g" % round(float(value), 6)


def describe_values(values, scale=1.0):
    """Text of the distinct control values of a bucket: 'unknown' if there are none, the value if there is one, 'varies: a, b, ...' if
    there are several. Each value is multiplied by scale first (100.0 is used for p).
    """
    texts = [fmt_x(scale * float(v)) for v in values]
    if not texts:
        return "unknown"
    if len(texts) == 1:
        return texts[0]
    return "varies: " + ", ".join(texts)


def count_range(values):
    """'n' or 'low-high' over the integer entries (bool excluded); None if there are none."""
    present = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
    if not present:
        return None
    low, high = min(present), max(present)
    return str(low) if low == high else "%d-%d" % (low, high)


# Example for the function below, by hand calculation (the fill order of matplotlib is not verified): [GLR, TBR, CGR, TSR] is returned
# as [GLR, CGR, TBR, TSR]; [GLR, TBR, CGR, TSR, TBR-enum] as [GLR, CGR, TBR-enum, TBR, TSR]. The legend is placed 'upper right' in
# the bar figures and 'best' in the line figures.
def legend_order(items, ncol=2):
    """Reorder so that matplotlib's column-major legend fill shows the items row by row (unverified)."""
    rows = -(-len(items) // ncol)
    slots = [None] * (rows * ncol)
    for j, item in enumerate(items):
        row, col = divmod(j, ncol)
        slots[col * rows + row] = item
    return [item for item in slots if item is not None]


# A relative text is passed to Path(text).resolve(); this function does not use ROOT (the project folder). Allowed: a path that does
# not exist, or an existing empty folder. Refused: an existing file, a folder that cannot be listed, a folder that is not empty.
# Nothing is created here. main compares only whether --out and --style-demo are the same folder; nesting is not checked.
def check_target(text, label):
    """(resolved Path, None) when the folder may be used, else (None, message)."""
    path = Path(text).resolve()
    if path.exists():
        if not path.is_dir():
            return None, "%s exists and is not a folder: %s" % (label, ascii(str(path)))
        try:
            occupied = any(path.iterdir())
        except OSError as exc:
            return None, "%s folder cannot be listed: %s" % (label, ascii(str(exc)))
        if occupied:
            return None, "%s folder is not empty (nothing is overwritten): %s" % (label, ascii(str(path)))
    return path, None


# Import order: the first attempt uses the module search path as it is, so any ssn_hops found there is used; only after an ImportError
# is ROOT/src put at the front of sys.path and the import repeated (the second attempt catches any Exception and raises RuntimeError).
# Both prepare_plot_data and ENUM_POLICY_NAME are imported; ENUM_POLICY_NAME must equal ENUM_NAME of this file. sys.dont_write_bytecode
# is set to True first. Which package location was imported is not printed.
def load_core():
    """Return prepare_plot_data of the project; RuntimeError (ASCII text) when it cannot be imported."""
    sys.dont_write_bytecode = True
    try:
        from ssn_hops.experiment_plots import prepare_plot_data
        from ssn_hops.experiment_io import ENUM_POLICY_NAME
    except ImportError:
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        try:
            from ssn_hops.experiment_plots import prepare_plot_data
            from ssn_hops.experiment_io import ENUM_POLICY_NAME
        except Exception as exc:
            raise RuntimeError("cannot import ssn_hops.experiment_plots (tried the installed package and %s): %s: %s"
                               % (ascii(str(SRC)), type(exc).__name__, ascii(str(exc))))
    if ENUM_POLICY_NAME != ENUM_NAME:
        raise RuntimeError("the enumeration policy name of the project differs from this script: "
                           + ascii(str(ENUM_POLICY_NAME)))
    return prepare_plot_data


def read_summary(path):
    """Read the summary file with the codec utf-8-sig and parse it as JSON; ValueError if it cannot be read or parsed, or if it is
    not a JSON object.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read the summary as UTF-8 JSON: " + ascii(str(exc)))
    if not isinstance(data, dict):
        raise ValueError("the summary is not a JSON object")
    return data


def load_matplotlib():
    """Import matplotlib, select the Agg backend before pyplot is imported, and return a namespace with plt, ticker, Line2D, Patch and
    rc_context. ImportError is not caught here (main catches it). Line2D is not used elsewhere in this file.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import ticker
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    return SimpleNamespace(plt=plt, ticker=ticker, Line2D=Line2D, Patch=Patch, rc_context=matplotlib.rc_context)


# ----------------------------------------------------------------------------- data -> jobs

# Preferred bucket: grid 'interruption' for the axis failure_probability, grid 'size' for the axis n, variant 'reference' (fixed names
# in this script; they are not read from a suite). Otherwise the first candidate in the order of the specs, with a NOTICE line. Other
# buckets of the same axis are not drawn and are named in a NOTICE line. spec["grid"] and spec["variant"] are indexed without a guard.
def choose_spec(specs, axis, metric, notices):
    """The plot specification of prepare_plot_data for (axis, metric); preferred grid, else the first."""
    candidates = [s for s in specs if s.get("axis") == axis and s.get("metric") == metric]
    if not candidates:
        return None
    wanted = "interruption" if axis == "failure_probability" else "size"
    chosen = None
    for spec in candidates:
        if spec["grid"] == wanted and spec["variant"] == "reference":
            chosen = spec
            break
    if chosen is None:
        chosen = candidates[0]
        notices.append("NOTICE: no %s/reference bucket for axis %s; using %s/%s"
                       % (wanted, axis, chosen["grid"], chosen["variant"]))
    if len(candidates) > 1:
        others = ["%s/%s" % (s["grid"], s["variant"]) for s in candidates if s is not chosen]
        notices.append("NOTICE: axis %s has several buckets; not drawn: %s" % (axis, ", ".join(others)))
    return chosen


def distinct_controls(summary, spec, key):
    """Sorted distinct values of controls[key] over the groups of the bucket given by spec (grid, variant, axis); a group without a
    controls mapping, or whose value is not a finite number, adds nothing.
    """
    values = set()
    for group in summary["groups"]:
        if (group.get("grid"), group.get("variant"), group.get("axis")) == (spec["grid"], spec["variant"], spec["axis"]):
            controls = group.get("controls")
            if isinstance(controls, dict) and _num(controls.get(key)) is not None:
                values.add(controls[key])
    return sorted(values)


# Reads the summary directly: for every policy of summary['policy_names'] and every group of the bucket (sorted by x) the entry
# ['policies'][policy]['equal_replicate'][metric] with mean, se_of_mean and n_nonnull. A group without an entry for a listed policy
# raises KeyError here; make_jobs then skips the whole figure as malformed summary data. For TBR-enum the curve also carries
# completeness_share: enumeration_completeness.completeness_share_pooled of each group, None if that block is absent or not a mapping.
def curves_from_groups(summary, spec, metric):
    """Curves for a metric that prepare_plot_data does not export on this axis (loss versus N)."""
    groups = sorted([g for g in summary["groups"]
                     if (g["grid"], g["variant"], g["axis"]) == (spec["grid"], spec["variant"], spec["axis"])],
                    key=lambda g: g["x"])
    curves = []
    for policy in summary["policy_names"]:
        stats = [g["policies"][policy]["equal_replicate"][metric] for g in groups]
        curve = {"policy": policy, "x": [g["x"] for g in groups], "y": [s["mean"] for s in stats],
                 "se": [s["se_of_mean"] for s in stats], "nonnull_repetitions": [s["n_nonnull"] for s in stats]}
        if policy == ENUM_NAME:
            curve["completeness_share"] = [
                (g["enumeration_completeness"].get("completeness_share_pooled")
                 if isinstance(g.get("enumeration_completeness"), dict) else None)
                for g in groups]
        curves.append(curve)
    return curves


def series_from_curves(curves, xscale, yscale, keys, names):
    """Turn curves (dicts with policy, x, y, se and optionally completeness_share and nonnull_repetitions) into drawable series for the
    policies in keys, in the order of keys; return (series, sorted names of the curve policies that are not in keys).
    x is multiplied by xscale, y and its SE by yscale. The only factor this script uses is 100.0: x = 100 * p (percent) and
    loss = 100 * failure fraction (percent); the red completeness labels are printed as whole percent by the drawing functions.
    Delays and CPU times stay in seconds, N stays a count. A y or SE that is not a finite number (bool counts as not a number)
    becomes None, a missing point. A key that has no curve is skipped without a note.
    """
    by_key = {}
    for curve in curves:
        by_key[curve.get("policy")] = curve
    series = []
    for key in keys:
        curve = by_key.get(key)
        if curve is None:
            continue
        xs = [xscale * float(v) for v in curve["x"]]
        ys = []
        ses = []
        for y, se in zip(curve["y"], curve["se"]):
            y = _num(y)
            se = _num(se)
            if y is None:
                ys.append(None)
                ses.append(None)
            else:
                ys.append(yscale * y)
                ses.append(None if se is None else yscale * se)
        shares = curve.get("completeness_share") if key == ENUM_NAME else None
        if shares is not None:
            shares = [_num(v) for v in shares]
        series.append({"key": key, "name": names.get(key, key), "x": xs, "y": ys, "se": ses,
                       "share": shares, "n": curve.get("nonnull_repetitions")})
    ignored = sorted(str(k) for k in by_key if k not in keys)
    return series, ignored


def prune(series, xs):
    """Drop series and x positions without any value; list every absence in notes."""
    notes = []
    kept = [s for s in series if any(v is not None for v in s["y"])]
    gone = [s["name"] for s in series if not any(v is not None for v in s["y"])]
    if gone:
        notes.append("No data in this summary, series not drawn: " + ", ".join(gone))
    if not kept:
        return [], [], notes
    keep_idx = [i for i in range(len(xs)) if any(s["y"][i] is not None for s in kept)]
    dropped = [fmt_x(xs[i]) for i in range(len(xs)) if i not in keep_idx]
    if dropped:
        notes.append("No data at x = " + ", ".join(dropped) + " (position not drawn)")
    new_xs = [xs[i] for i in keep_idx]
    out = []
    for s in kept:
        t = dict(s)
        for field in ("x", "y", "se"):
            t[field] = [s[field][i] for i in keep_idx]
        for field in ("share", "n"):
            if s[field] is not None:
                t[field] = [s[field][i] for i in keep_idx]
        out.append(t)
    missing = []
    for s in out:
        for i, y in enumerate(s["y"]):
            if y is None:
                missing.append("%s at %s" % (s["name"], fmt_x(new_xs[i])))
    if missing:
        notes.append("Missing points (absent, never drawn as zero): " + "; ".join(missing))
    return out, new_xs, notes


# Missing policies and values: a policy of keys that has no curve in the summary is skipped without any note (the legend simply lacks
# it); a series with only missing values is dropped and named in 'No data in this summary, series not drawn'; an x position where no
# series has a value is dropped ('No data at x = ...'); a single missing point stays a gap and is listed ('Missing points (absent,
# never drawn as zero)'); policies of the curves that this figure does not draw are listed ('Policies of the summary not drawn in this
# figure'). None is returned, with a reason, if no series exists, no series has a value, or (logarithmic axis) no value is positive.
def make_job(base, kind, curves, partial, xlabel, ylabel, subtitle, extra_notes,
             xscale=1.0, yscale=1.0, keys=ORDER, names=NAMES, logy=False):
    """(job, None) or (None, reason)."""
    series, ignored = series_from_curves(curves, xscale, yscale, keys, names)
    if not series:
        return None, "no drawable policy in the summary for this figure"
    # All series of one figure are assumed to have the same x positions, in the same order, as the FIRST series (the first policy of
    # keys that has a curve); this is not checked. The tick labels come from that series; bars are placed by position index. A later
    # series with fewer points can make prune raise IndexError (make_jobs reports it as malformed summary data); surplus points of a
    # longer series are ignored; a series of the same length with other x values is drawn without a warning.
    series, xs, prune_notes = prune(series, series[0]["x"])
    if not series:
        return None, "no policy has any value for this figure"
    if logy and not any(v is not None and v > 0 for s in series for v in s["y"]):
        return None, "no positive value for a logarithmic axis"
    notes = [NOTE_MAIN] + list(extra_notes)
    if any(s["key"] == ENUM_NAME for s in series):
        notes.append(NOTE_ENUM)
    if partial:
        notes.insert(0, NOTE_PARTIAL)
    if ignored:
        notes.append("Policies of the summary not drawn in this figure: " + ", ".join(ignored))
    notes += prune_notes
    title = TITLE_HEAD + (" / PARTIAL" if partial else "") + "\n" + subtitle
    return {"base": base, "kind": kind, "series": series, "xs": xs, "xlabels": [fmt_x(v) for v in xs],
            "xlabel": xlabel, "ylabel": ylabel, "title": title, "notes": notes, "logy": logy,
            "top": 0.88, "banner": None, "ylim_top": None, "major_step": None}, None


# Figures and their sources: fig3a_delay_vs_p (axis failure_probability, delivered_mean_delay_s) and fig3b_loss_vs_p (axis
# failure_probability, failure_fraction); x of both and y of the loss are multiplied by 100. fig4_delay_vs_N (axis n,
# delivered_mean_delay_s, bars); fig4_loss_vs_N (axis n, bars; failure_fraction read from the groups by curves_from_groups, y times
# 100); fig5_cost_vs_N and fig5_cost_vs_N_logy (axis n, route_seconds_per_call, lines, only the policies of COST_KEYS, so TSR is not
# drawn). attempt() turns a KeyError, TypeError, ValueError or IndexError raised inside make_job into a skipped figure ('malformed
# summary data'). 'partial' is true when summary['complete'] is not True, whatever --allow-partial says; --allow-partial is only
# passed to prepare_plot_data in main.
def make_jobs(summary, data):
    """Return (jobs, skipped [(name, reason)], notices) from the validated summary."""
    specs = data["plots"]
    partial = summary.get("complete") is not True
    notices = []
    jobs = []
    skipped = []

    def attempt(base, **kwargs):
        try:
            job, reason = make_job(base, partial=partial, **kwargs)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            job, reason = None, "malformed summary data: " + ascii(str(exc))
        if job is None:
            skipped.append((base, reason))
        else:
            jobs.append(job)

    spec_d = choose_spec(specs, "failure_probability", "delivered_mean_delay_s", notices)
    spec_l = choose_spec(specs, "failure_probability", "failure_fraction", notices)
    if spec_d is None:
        skipped.append(("fig3a_delay_vs_p", "no failure_probability group in the summary"))
    else:
        n_text = describe_values(distinct_controls(summary, spec_d, "n"))
        attempt("fig3a_delay_vs_p", kind="lines", curves=spec_d["curves"], xscale=100.0,
                xlabel="Interruption probability (%)", ylabel="End-to-end transmission delay (second)",
                subtitle="Transmission delay vs. interruption probability (N = %s)" % n_text,
                extra_notes=[NOTE_P, NOTE_DELAY, NOTE_STYLE])
    if spec_l is None:
        skipped.append(("fig3b_loss_vs_p", "no failure_probability group in the summary"))
    else:
        n_text = describe_values(distinct_controls(summary, spec_l, "n"))
        attempt("fig3b_loss_vs_p", kind="lines", curves=spec_l["curves"], xscale=100.0, yscale=100.0,
                xlabel="Interruption probability (%)", ylabel="Loss (%)",
                subtitle="Loss vs. interruption probability (N = %s)" % n_text,
                extra_notes=[NOTE_P, NOTE_LOSS, NOTE_STYLE])

    spec_n = choose_spec(specs, "n", "delivered_mean_delay_s", notices)
    spec_c = choose_spec(specs, "n", "route_seconds_per_call", notices)
    if spec_n is None:
        skipped.append(("fig4_delay_vs_N", "no size (axis n) group in the summary"))
        skipped.append(("fig4_loss_vs_N", "no size (axis n) group in the summary"))
    else:
        p_text = describe_values(distinct_controls(summary, spec_n, "failure_probability"), 100.0)
        attempt("fig4_delay_vs_N", kind="bars", curves=spec_n["curves"],
                xlabel="Network scale", ylabel="End-to-end transmission delay (second)",
                subtitle="Transmission delay vs. network scale (interruption probability p = %s%%)" % p_text,
                extra_notes=[NOTE_FIG4, NOTE_DELAY])
        try:
            loss_curves = curves_from_groups(summary, spec_n, "failure_fraction")
        except (KeyError, TypeError, IndexError) as exc:
            loss_curves = None
            skipped.append(("fig4_loss_vs_N", "malformed summary data: " + ascii(str(exc))))
        if loss_curves is not None:
            attempt("fig4_loss_vs_N", kind="bars", curves=loss_curves, yscale=100.0,
                    xlabel="Network scale", ylabel="Loss (%)",
                    subtitle=("EXTRA figure, not present in the paper (its Fig. 4 has no loss panel): loss vs. "
                              "network scale (p = %s%%)" % p_text),
                    extra_notes=[NOTE_LOSS, "same style as paper Fig. 4; the paper has no counterpart of this figure"])
    if spec_c is None:
        skipped.append(("fig5_cost_vs_N", "no route_seconds_per_call data on the size axis"))
        skipped.append(("fig5_cost_vs_N_logy", "no route_seconds_per_call data on the size axis"))
    else:
        reason = spec_c.get("exclusion_reason", "paper Fig.5 legend: GLR, TBR, CGR only")
        extra = [NOTE_COST, "TSR is omitted as in revision 3b (rule: %s)" % reason, NOTE_STYLE]
        for base, logy in (("fig5_cost_vs_N", False), ("fig5_cost_vs_N_logy", True)):
            attempt(base, kind="lines", curves=spec_c["curves"], keys=COST_KEYS, names=COST_NAMES, logy=logy,
                    xlabel="Network scale", ylabel="CPU seconds per route call (this implementation)",
                    subtitle="Cost vs. network scale" + (" (logarithmic y axis)" if logy else " (linear y axis)"),
                    extra_notes=extra)
    return jobs, skipped, notices


# The demo uses the four policies ORDER[:4] (no TBR-enum), no SE bars, the red banner, the y range 0 to 16 with major step 2 and the
# interruption probability 4% in the title (the written by-eye description of the paper's Fig. 4 gives that range, step and caption).
# make_demo_job itself needs no summary and no ssn_hops; one file, fig4_style_demo.png. If the summary step of the same command ends
# with exit code 3, the demo is not drawn (see the exit-code comment above EXIT_OK).
def make_demo_job():
    """Style demo: the by-eye table of the paper, drawn by the same draw_bars as fig4_delay_vs_N."""
    series = []
    for key in ORDER[:4]:
        series.append({"key": key, "name": NAMES[key], "x": [float(n) for n in DEMO_N],
                       "y": [float(v) for v in DEMO_HEIGHTS[key]], "se": [None] * len(DEMO_N),
                       "share": None, "n": None})
    notes = ["Heights are BY-EYE readings (+-0.15 s) of Fig. 4 of arXiv 2108.08523v1, taken from "
             "Repo_Orchestrator_2/final/PAPER_FIG4_DESCRIPTION.md; no code of this project produced them.",
             "Purpose: compare the STYLE (grouped bars, colours, hatching, legend, fonts) with the paper's picture "
             "without running any experiment. These numbers are never drawn in a figure that shows our data.",
             "The paper's axis-label typo is not copied; y range 0-16 with major step 2 as described."]
    return {"base": "fig4_style_demo", "kind": "bars", "series": series, "xs": [float(n) for n in DEMO_N],
            "xlabels": [str(n) for n in DEMO_N], "xlabel": "Network scale",
            "ylabel": "End-to-end transmission delay (second)",
            "title": "Style of paper Fig. 4: transmission delay vs. network scale (interruption probability = 4%)",
            "notes": notes, "logy": False, "top": 0.80, "banner": DEMO_BANNER,
            "ylim_top": 16.0, "major_step": 2.0}


# ----------------------------------------------------------------------------- drawing

def style_axes(mpl, ax, logy):
    """Grid under the data at the major y ticks (none on x), inward ticks also on the top and right axes, major tick label size 11;
    minor y ticks only when the y axis is not logarithmic.
    """
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", color=GRID_COLOR, linewidth=0.8)
    ax.xaxis.grid(False)
    ax.tick_params(axis="both", which="both", direction="in", top=True, right=True)
    ax.tick_params(axis="both", which="major", labelsize=11)
    if not logy:
        ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))


def finish_legend(ax, handles, location):
    """Legend of the handles, reordered by legend_order(handles, 2), in two columns with a black frame, at the given location."""
    ax.legend(handles=legend_order(handles, 2), loc=location, ncol=2, frameon=True, fancybox=False,
              edgecolor="black", framealpha=1.0, fontsize=11)


# Group centres are at 0, 1, 2, ... (the tick positions); each bar is 0.8 / (number of series) wide and the bars of a group are placed
# symmetrically around the group centre. SE bars are drawn only if with_se is true and the point has an SE. A point with a completeness
# share (TBR-enum) gets a red percent label above the bar, above the SE bar if one is drawn. y axis from 0 to 1.35 times the largest
# drawn value (bar plus SE), or to 1.0 if that value is not positive, or to job['ylim_top'] if that is set (the demo: 16, with major
# step 2). The legend is at 'upper right'. Returns the largest drawn value.
def draw_bars(mpl, ax, job, with_se):
    """Grouped bars: one group per x, one bar per series in series order; a missing value leaves a gap."""
    series = job["series"]
    count = len(series)
    width = 0.8 / count
    top = 0.0
    handles = []
    for index, s in enumerate(series):
        style = STYLE[s["key"]]
        offset = (index - (count - 1) / 2.0) * width
        xs, ys, ex, ey, ee = [], [], [], [], []
        for g, y in enumerate(s["y"]):
            if y is None:
                continue
            x = g + offset
            se = s["se"][g] if with_se else None
            xs.append(x)
            ys.append(y)
            top = max(top, y + (se or 0.0))
            if se is not None:
                ex.append(x)
                ey.append(y)
                ee.append(se)
            share = s["share"][g] if s["share"] is not None else None
            if share is not None:
                ax.text(x, y + (se or 0.0), "%.0f%%" % (100.0 * share), ha="center", va="bottom",
                        fontsize=8, color=SHARE_COLOR, zorder=5)
        ax.bar(xs, ys, width=width, color=style["color"], edgecolor="black", hatch=style["hatch"],
               linewidth=1.0, zorder=3)
        if ee:
            ax.errorbar(ex, ey, yerr=ee, fmt="none", ecolor="black", elinewidth=1.0, capsize=3, zorder=4)
        handles.append(mpl.Patch(facecolor=style["color"], edgecolor="black", hatch=style["hatch"],
                                 linewidth=1.0, label=s["name"]))
    ax.set_xticks(list(range(len(job["xlabels"]))))
    ax.set_xticklabels(job["xlabels"])
    ax.set_xlim(-0.6, len(job["xlabels"]) - 0.4)
    if job["ylim_top"] is not None:
        ax.set_ylim(0.0, job["ylim_top"])
    else:
        ax.set_ylim(0.0, 1.35 * top if top > 0 else 1.0)
    if job["major_step"] is not None:
        ax.yaxis.set_major_locator(mpl.ticker.MultipleLocator(job["major_step"]))
    finish_legend(ax, handles, "upper right")
    return top


# Tick positions and labels are those of job['xs'] and job['xlabels'] (see the assumption comment in make_job: the first series).
# Linear axis: y from 0 to 1.15 times the largest drawn value (point plus SE), or to 1.0 if that value is not positive; logarithmic
# axis (job['logy']): log scale, and no explicit y limits are set here. Legend position 'best'. Red percent labels (TBR-enum
# completeness share) are placed 8 points above the point. Returns the largest drawn value.
def draw_lines(mpl, ax, job, with_se):
    """One line with markers per series; a missing value is NaN: no marker, the line is broken there."""
    top = 0.0
    handles = []
    for s in job["series"]:
        style = STYLE[s["key"]]
        values = [math.nan if y is None else y for y in s["y"]]
        line, = ax.plot(s["x"], values, color=style["color"], marker=style["marker"], markersize=7,
                        markeredgecolor="black", linewidth=1.8, zorder=3, label=s["name"])
        handles.append(line)
        ex, ey, ee = [], [], []
        for g, y in enumerate(s["y"]):
            if y is None:
                continue
            se = s["se"][g] if with_se else None
            top = max(top, y + (se or 0.0))
            if se is not None:
                ex.append(s["x"][g])
                ey.append(y)
                ee.append(se)
            share = s["share"][g] if s["share"] is not None else None
            if share is not None:
                ax.annotate("%.0f%%" % (100.0 * share), (s["x"][g], y), textcoords="offset points",
                            xytext=(0, 8), ha="center", fontsize=8, color=SHARE_COLOR, zorder=5)
        if ee:
            ax.errorbar(ex, ey, yerr=ee, fmt="none", ecolor="black", elinewidth=1.0, capsize=3, zorder=4)
    ax.set_xticks(job["xs"])
    ax.set_xticklabels(job["xlabels"])
    if job["logy"]:
        ax.set_yscale("log")
    else:
        ax.set_ylim(0.0, 1.15 * top if top > 0 else 1.0)
    finish_legend(ax, handles, "best")
    return top


def se_note(job):
    """SE_NOTE, followed by ' Non-null repetitions per point: ...' that gives, for each series with counts, the single count or the
    low-high range over its drawn points.
    """
    parts = []
    for s in job["series"]:
        if s["n"] is not None:
            text = count_range([n for n, y in zip(s["n"], s["y"]) if y is not None])
            if text:
                parts.append("%s %s" % (s["name"], text))
    return SE_NOTE + (" Non-null repetitions per point: " + ", ".join(parts) + "." if parts else "")


# Layout numbers are this script's own choices: figure 8.0 x 6.6 inches, dpi 150, margins (left 0.12, right 0.97, top job['top'],
# bottom 0.12 plus 0.021 per printed note line), notes wrapped at 125 characters, font sizes (axis labels 12, title 10, notes 7.5,
# banner 12), bar width 0.8 per group, y limit factors 1.35 (bars) and 1.15 (lines), marker size 7, line width 1.8. The written
# by-eye description of the paper's Fig. 4 gives none of these numbers (only style words and, for the demo, the y range 0-16 with
# major step 2). The code makes no check that the notes fit in the bottom margin.
def render(mpl, job, with_se, path):
    """Draw one job into the PNG file path. The notes (plus se_note(job) when with_se) are wrapped first; then a figure of 8.0 x 6.6
    inches is made, the margins set, the axes drawn (bars or lines by job['kind']), labels and title set, the banner added if the job
    has one, the note block written at the lower left in grey, and the file saved with dpi 150. The figure is closed in a finally
    block. An exception is not caught here: write_figures reports it for that file and goes on with the next file.
    """
    notes = list(job["notes"])
    if with_se:
        notes.append(se_note(job))
    lines = []
    for note in notes:
        lines += textwrap.wrap(note, width=125, initial_indent="- ", subsequent_indent="  ")
    with mpl.rc_context(RC):
        fig, ax = mpl.plt.subplots(figsize=(8.0, 6.6))
        try:
            fig.subplots_adjust(left=0.12, right=0.97, top=job["top"], bottom=0.12 + 0.021 * len(lines))
            style_axes(mpl, ax, job["logy"])
            if job["kind"] == "bars":
                draw_bars(mpl, ax, job, with_se)
            else:
                draw_lines(mpl, ax, job, with_se)
            ax.set_xlabel(job["xlabel"], fontsize=12)
            ax.set_ylabel(job["ylabel"], fontsize=12)
            ax.set_title(job["title"], fontsize=10)
            if job["banner"]:
                fig.text(0.5, 0.985, job["banner"], ha="center", va="top", fontsize=12, color="#b00000",
                         bbox={"facecolor": "#ffe0e0", "edgecolor": "#b00000", "pad": 4.0})
            fig.text(0.01, 0.008, "\n".join(lines), ha="left", va="bottom", fontsize=7.5, color="#666666",
                     fontweight="normal", linespacing=1.2)
            fig.savefig(str(path), dpi=150)
        finally:
            mpl.plt.close(fig)


# Disk effects of the script: nothing is written before the argument and folder checks have passed. The target folder is created here
# (mkdir with parents) just before the first file is drawn: the --out folder only if at least one job exists, the --style-demo folder
# whenever the demo is drawn. Files: <name>.png and <name>_se.png for each job of a summary (up to 12 files for the six figures),
# fig4_style_demo.png for the demo. A figure that fails is reported and the others are still written; nothing is deleted, so a later run
# into a folder that now holds files is refused by check_target. This script does not overwrite existing files: a non-empty target
# folder is refused before anything is written.
def write_figures(mpl, jobs, folder, with_se_variant):
    """Write the files of the jobs; return (written paths, failed names)."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    failed = []
    for job in jobs:
        variants = [(False, job["base"] + ".png")]
        if with_se_variant:
            variants.append((True, job["base"] + "_se.png"))
        for with_se, name in variants:
            path = folder / name
            try:
                render(mpl, job, with_se, path)
                written.append(path)
            except Exception as exc:
                failed.append(name)
                print("ERROR: figure %s failed while drawing: %s: %s" % (name, type(exc).__name__, ascii(str(exc))))
    return written, failed


# ----------------------------------------------------------------------------- command line

def parse_args(argv):
    """Parse the command line (options --summary, --out, --style-demo, --allow-partial). parser.error is called if none of --summary,
    --out and --style-demo is given, or if only one of --summary and --out is given. The paths stay text here; check_target resolves them.
    """
    parser = argparse.ArgumentParser(
        prog="paper_style_plots.py",
        description="Paper-style figures from a summary.json (reconstruction, not the authors' results).")
    parser.add_argument("--summary", help="summary.json of an experiment run (needs --out)")
    parser.add_argument("--out", help="output folder; must not exist or must be empty (needs --summary)")
    parser.add_argument("--style-demo", metavar="DIR",
                        help="write fig4_style_demo.png (by-eye paper values, NOT our results) into DIR")
    parser.add_argument("--allow-partial", action="store_true",
                        help="accept an incomplete summary and label the figures PARTIAL")
    args = parser.parse_args(argv)
    if args.summary is None and args.out is None and args.style_demo is None:
        parser.error("give --summary and --out, or --style-demo, or both")
    if (args.summary is None) != (args.out is None):
        parser.error("--summary and --out must be given together")
    return args


def main(argv=None):
    """Run the script and return an exit code (see the exit-code comment above EXIT_OK). Order: check the --out and --style-demo
    folders (check_target); if --summary is given: load_core, read_summary, prepare_plot_data, make_jobs, then print the NOTICE and
    SKIPPED lines; then import matplotlib; then write the summary figures (only if there is at least one job) and the demo figure;
    then print the WROTE lines and the count line and return the code. The summary step comes before the matplotlib import and
    before the demo.
    """
    args = parse_args(argv)
    problems = []
    out_dir = None
    demo_dir = None
    if args.out is not None:
        out_dir, problem = check_target(args.out, "--out")
        if problem:
            problems.append(problem)
    if args.style_demo is not None:
        demo_dir, problem = check_target(args.style_demo, "--style-demo")
        if problem:
            problems.append(problem)
    if out_dir is not None and demo_dir is not None and out_dir == demo_dir:
        problems.append("--out and --style-demo must be different folders")
    if problems:
        for problem in problems:
            print("ERROR: " + problem)
        return EXIT_USAGE

    jobs = []
    skipped = []
    if args.summary is not None:
        try:
            prepare = load_core()
        except RuntimeError as exc:
            print("ERROR: " + str(exc))
            print("Nothing was written.")
            return EXIT_INPUT
        try:
            summary = read_summary(args.summary)
            data = prepare(summary, None, args.allow_partial)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            print("ERROR: the summary is refused: %s: %s" % (type(exc).__name__, ascii(str(exc))))
            print("Nothing was written.")
            return EXIT_INPUT
        jobs, skipped, notices = make_jobs(summary, data)
        for notice in notices:
            print(notice)
        for name, reason in skipped:
            print("SKIPPED figure %s: %s" % (name, reason))

    try:
        mpl = load_matplotlib()
    except ImportError as exc:
        print("ERROR: matplotlib cannot be imported: " + ascii(str(exc)))
        print("Nothing was written. Install: pip install matplotlib")
        return EXIT_RENDER

    written = []
    failed = []
    if args.summary is not None:
        if jobs:
            done, bad = write_figures(mpl, jobs, out_dir, True)
            written += done
            failed += bad
        else:
            print("No figure could be drawn from this summary; the folder %s was not created." % ascii(str(out_dir)))
    if demo_dir is not None:
        done, bad = write_figures(mpl, [make_demo_job()], demo_dir, False)
        written += done
        failed += bad
    for path in written:
        print("WROTE " + ascii(str(path)))
    print("paper_style_plots: %d file(s) written, %d figure(s) skipped, %d file(s) failed"
          % (len(written), len(skipped), len(failed)))
    if failed:
        return EXIT_RENDER
    if not written:
        return EXIT_NOFIG
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
