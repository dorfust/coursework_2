"""Plan loading and binding checks for the M1 driver (project interfaces only; nothing is run here).

A plan is bound to an absolute root, to a revision and to the source file hashes of the installed
ssn_hops package (experiment_io.execution_guard / validate_plan, blob 0119dfc5). Every slice of ONE plan
must run under the SAME root path, the same revision and the same source bytes. This module checks
those bindings BEFORE the project's own guards run, so that a refusal names the concrete difference.
"""
import hashlib
import json
from pathlib import Path

from ssn_hops import experiment_io as eio


class BindingError(ValueError):
    """The plan, root, revision or source files do not match this execution environment."""


def source_hash_of(sources):
    """One sha256 over the planned per-file source hash map (recorded in the ledger)."""
    text = json.dumps(sources, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_binding(document, plan_path, revision, *, current_sources=None, expected_plan_sha256=None):
    """Raise BindingError with a precise message on a root / plan-hash / revision / source mismatch.

    ``document`` is the parsed plan.json; ``current_sources`` defaults to experiment_io.source_hashes().
    """
    try:
        body = document["body"]
        planned_root = Path(body["root"]).resolve()
        planned_revision = body["revision"]
        planned_sources = body["source_sha256"]
    except (KeyError, TypeError, OSError):
        raise BindingError("plan.json has no usable body/root/revision/source_sha256") from None
    plan_dir = Path(plan_path).resolve().parent
    if planned_root != plan_dir:
        raise BindingError(f"root mismatch: the plan was created for root {planned_root} but plan.json is at "
                           f"{plan_dir}; all slices must run under the planned absolute root (plan moved)")
    if expected_plan_sha256 is not None and document.get("sha256") != expected_plan_sha256:
        raise BindingError(f"plan sha256 mismatch: file has {document.get('sha256')}, expected {expected_plan_sha256}")
    if revision != planned_revision:
        raise BindingError(f"revision mismatch: supplied {revision}, planned {planned_revision}")
    current = eio.source_hashes() if current_sources is None else current_sources
    if current != planned_sources:
        names = sorted(k for k in set(current) | set(planned_sources) if current.get(k) != planned_sources.get(k))
        raise BindingError("source hash mismatch: the installed ssn_hops bytes differ from the planned bytes in "
                           + ", ".join(names[:12]) + (" ..." if len(names) > 12 else "")
                           + "; create a new plan or install the planned revision")


class PlanView:
    """Read-only lookups over a loaded plan dict (scenario/cell/seed index/trace owner)."""

    def __init__(self, plan):
        self.plan = plan
        self.body = plan["body"]
        self.sha256 = plan["sha256"]
        self.revision = self.body["revision"]
        self.root = Path(self.body["root"])
        self.cells = list(self.body["cells"])
        self.cell_by_id = {c["id"]: c for c in self.cells}
        self.scenarios = list(self.body["scenarios"])
        self.scenario_by_id = {s["id"]: s for s in self.scenarios}
        self.seed_tuples = self.body["suite"]["seed_tuples"]
        owners = {}
        for scenario in self.scenarios:
            owners.setdefault(scenario["trace_path"], scenario)
        self.trace_owner_by_path = owners

    def cell(self, cell_id):
        if cell_id not in self.cell_by_id:
            raise ValueError(f"{cell_id} is not a cell of this plan (unknown, or absent by design)")
        return self.cell_by_id[cell_id]

    def scenario(self, scenario_id):
        return self.scenario_by_id[scenario_id]

    def scenario_of(self, cell):
        return self.scenario_by_id[cell["scenario"]]

    @staticmethod
    def scenario_n(scenario):
        return scenario["config"]["orbit"]["n"]

    @staticmethod
    def scenario_p(scenario):
        return scenario["config"]["failure_probability"]

    def seed_index(self, scenario):
        """Position of the scenario's seed tuple in suite['seed_tuples'] (the policy_scope index)."""
        return self.seed_tuples.index(scenario["seeds"])

    def policies(self):
        return list(self.body["policies"])

    @property
    def source_hash(self):
        return source_hash_of(self.body["source_sha256"])


def load_readonly(plan_path):
    """Validate the plan with the project's load_plan (hash, files, scoped checks); no execution guard."""
    return PlanView(eio.load_plan(plan_path))


def load_for_execution(plan_path, revision, *, expected_plan_sha256=None, current_sources=None):
    """check_binding, then load_plan, then execution_guard (authoritative, same as execute_suite)."""
    document = eio.read(plan_path)
    check_binding(document, plan_path, revision, current_sources=current_sources,
                  expected_plan_sha256=expected_plan_sha256)
    plan = eio.load_plan(plan_path)
    eio.execution_guard(plan, revision)
    return PlanView(plan)


def mark_started(view):
    """Mirror of execute_suite's execution_started.json {plan_sha256, revision}; no-op when present.

    The aggregator never reads this file; it exists only so that a staged root looks like a started one.
    """
    try:
        eio.write(view.root / "execution_started.json", {"plan_sha256": view.sha256, "revision": view.revision})
        return True
    except FileExistsError:
        return False
