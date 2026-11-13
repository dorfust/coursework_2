"""Optional policy TBR_enumeration: full enumeration of simple paths at every hop.

Runtime status: NOT executed by its authors. OFF by default; it is planned only when the
plan option include_tbr_enumeration is switched on (see INTEGRATION_PLAN.md of T125).

WHAT IT DECIDES (identical to tbr_reference.exhaustive_simple_path_reference whenever
the search completes, see PLAN_CHECK_T125.md for the argument):
  * paths: all simple paths from packet.location to packet.destination that avoid
    blocked = packet.visited minus {packet.location}; the FIRST hop must lie in
    context.permitted_neighbors minus packet.visited; later hops are not restricted
    to permitted_neighbors; the destination is terminal (a path ends where it first
    reaches the destination);
  * objective: minimise (number of edges, then the full path as a tuple of node ids,
    lexicographically);
  * decision: Decision(path[1], context.tick); no admissible path -> None (the packet
    waits); packet.location == packet.destination -> None (zero hop, never forward to
    the current node).

HOW (iterative deepening, explicit stack, no recursion): for depth limit k = 1, 2, ...
enumerate ALL admissible simple prefixes of at most k edges in depth-first lexicographic
order. A prefix that reaches the destination is terminal; a prefix with exactly k edges
that is not at the destination is a frontier prefix and is not extended. After level k:
if at least one destination path was entered, return the smallest (edges, path) among
them; otherwise, if the level had no frontier prefix, there is no route; otherwise go on
with k + 1 (k stops at n - 1, the longest possible simple path). There is NO breadth-first
search, NO distance computation, NO pruning by distances, NO early return on the first
destination path and NO caching across calls (a per-call row cache of the adjacency is
only a speed-up of reading the same matrix).

COST: one expansion = one prefix entered (the unit of tbr_reference); every level starts
again from the root, so the expansions of a call are the sum over the levels k = 1 .. d*
of the number of admissible prefixes of at most k edges, where d* is the shortest
restricted distance. That number grows roughly like (branching factor) ** d*, i.e.
exponentially in d*. It is NOT the cost of the paper's brute force (which is unspecified)
and it will not complete on large dense graphs; no timing is claimed here.

BUDGETS (safety controls, NOT paper settings):
  * max_call_expansions: a call that has entered that many prefixes and still has a
    prefix left is INCOMPLETE. It returns None (the packet waits this tick), is counted,
    and NEVER yields a route from partial work and NEVER falls back to another router.
  * max_cell_expansions: when the cumulative expansions of this policy instance (one
    simulation cell) exceed it, the policy is exhausted: every later call returns None at
    once and is counted as skipped. The call that crosses the limit finishes normally, so
    the total can exceed the limit by at most max_call_expansions.
STATS NOTE: max_depth_completed is the deepest level (depth limit k) finished by ANY call,
incomplete calls included (the levels an incomplete call finished before it stopped); a
zero-hop call counts 0. It is a diagnostic only and takes part in no decision.
Instances are for sequential use in one cell. All values in stats() are JSON-serialisable.

NOTES ADDED LATER (text only, no code change):
  * INTEGRATION_PLAN.md of T125 and PLAN_CHECK_T125.md are documents of the project history
    (task T125), not source files of this package.
  * The status line 'NOT executed by its authors' describes the state when the module was
    written; later runs by the user are not reflected in this text.
"""
from numbers import Integral

import numpy as np

from .policies import Decision
from .tbr_reference import OBJECTIVE

POLICY_NAME = "TBR_enumeration"
SEARCH_IDENTITY = "iterative_deepening_full_enumeration_v1"
# Defaults 200000 (per call) and 200000000 (per cell): safety limits, not paper settings (see BUDGETS
# in the module docstring). After the cell limit is crossed every later call returns None at once
# (counted as skipped), so routing in that cell effectively stops and the packets wait.
DEFAULT_MAX_CALL_EXPANSIONS = 200000
DEFAULT_MAX_CELL_EXPANSIONS = 200000000


def _budget(value, name):
    # NumPy integers are Integral; Python and NumPy booleans are not budgets.
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(name + " must be a positive integer, not bool")
    if value <= 0:
        raise ValueError(name + " must be a positive integer")
    return int(value)


def _node(value, n, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(name + " must be an integer node id, not bool")
    node = int(value)
    if not 0 <= node < n:
        raise ValueError(name + " must satisfy 0 <= id < " + str(n))
    return node


class TBR_enumeration:
    """Full-enumeration TBR (iterative deepening) with explicit safety budgets."""

    name = POLICY_NAME

    def __init__(self, *, max_call_expansions=DEFAULT_MAX_CALL_EXPANSIONS,
                 max_cell_expansions=DEFAULT_MAX_CELL_EXPANSIONS):
        self._max_call_expansions = _budget(max_call_expansions, "max_call_expansions")
        self._max_cell_expansions = _budget(max_cell_expansions, "max_cell_expansions")
        self._policy_calls = 0
        self._complete_route = 0
        self._complete_no_route = 0
        self._complete_zero_hop = 0
        self._incomplete_call_budget = 0
        self._skipped_after_cell_budget = 0
        self._total_expansions = 0
        self._complete_expansions_sum = 0
        self._complete_expansions_max = 0
        self._incomplete_expansions_sum = 0
        self._max_depth_completed = 0
        self._cell_budget_exhausted = False

    @property
    def max_call_expansions(self):
        return self._max_call_expansions

    @property
    def max_cell_expansions(self):
        return self._max_cell_expansions

    def _search(self, adjacency, source, destination, first_hops, blocked):
        """Iterative deepening; returns (status, path, expansions, levels_completed).

        status is 'route', 'no_route' or 'incomplete'. An incomplete result carries no
        path. One expansion = one prefix popped from the stack (the root included, once
        per level). As in tbr_reference, the budget is exceeded only if another prefix
        remains after max_call_expansions entries.
        """
        n = adjacency.shape[0]
        budget = self._max_call_expansions
        # rows: per-call cache of adjacency rows (ascending neighbour ids), only a speed-up; it is local to this call.
        rows = {}
        expansions = 0
        levels_done = 0
        # limit stops at n - 1 because a simple path has at most n - 1 edges; if the loop ends without a
        # return, the return after the loop answers 'no_route' (the frontier of the last level cannot be extended).
        for limit in range(1, n):
            # Every level starts again from the root, so the root is popped and counted once per level.
            stack = [(source,)]
            best = None
            frontier = 0
            while stack:
                if expansions == budget:
                    return "incomplete", None, expansions, levels_done
                path = stack.pop()
                expansions += 1
                current = path[-1]
                if current == destination:
                    if best is None or (len(path), path) < (len(best), best):
                        best = path
                    continue  # the destination is terminal
                if len(path) - 1 == limit:
                    frontier += 1
                    continue  # frontier prefix: not extended at this level
                row = rows.get(current)
                if row is None:
                    row = tuple(int(v) for v in np.flatnonzero(adjacency[current]))
                    rows[current] = row
                # Reversed insertion + LIFO pop = ascending neighbour ids = lexicographic order.
                for neighbor in reversed(row):
                    if neighbor in blocked or neighbor in path:
                        continue
                    if len(path) == 1 and neighbor not in first_hops:
                        continue
                    stack.append(path + (neighbor,))
            levels_done = limit
            if best is not None:
                return "route", best, expansions, levels_done
            if frontier == 0:
                return "no_route", None, expansions, levels_done
        return "no_route", None, expansions, levels_done

    def choose(self, packet, context):
        self._policy_calls += 1
        if self._cell_budget_exhausted:
            self._skipped_after_cell_budget += 1
            return None
        # ValueError (not caught by the Simulator, so the run stops) is raised if adjacency is not square, a node id is
        # not an integer in range, or a permitted neighbour is not an actual neighbour of the location. Symmetry and
        # binary values are not checked here: any non-zero entry of adjacency counts as an edge.
        adjacency = np.asarray(context.adjacency)
        if adjacency.ndim != 2 or adjacency.shape[0] != adjacency.shape[1]:
            raise ValueError("adjacency must be a square matrix")
        n = adjacency.shape[0]
        source = _node(packet.location, n, "location")
        destination = _node(packet.destination, n, "destination")
        permitted = set()
        for value in context.permitted_neighbors:
            neighbor = _node(value, n, "permitted neighbor")
            if neighbor == source or not adjacency[source, neighbor]:
                raise ValueError("permitted neighbors must be actual neighbors of the location")
            permitted.add(neighbor)
        visited = {_node(value, n, "visited node") for value in packet.visited}
        if source == destination:
            # Zero hop, as in tbr_reference: the root is the destination; one prefix entered.
            self._complete_zero_hop += 1
            self._finish_call(1, 0, complete=True)
            return None
        first_hops = permitted - visited
        blocked = visited - {source}
        status, path, used, levels = self._search(adjacency, source, destination, first_hops, blocked)
        self._finish_call(used, levels, complete=status != "incomplete")
        if status == "route":
            self._complete_route += 1
            return Decision(path[1], context.tick)
        if status == "no_route":
            self._complete_no_route += 1
        else:
            self._incomplete_call_budget += 1
        return None  # no route, or an incomplete search: the packet waits

    def _finish_call(self, used, levels, complete):
        self._total_expansions += used
        if complete:
            self._complete_expansions_sum += used
            if used > self._complete_expansions_max:
                self._complete_expansions_max = used
        else:
            self._incomplete_expansions_sum += used
        if levels > self._max_depth_completed:
            self._max_depth_completed = levels
        if self._total_expansions > self._max_cell_expansions:
            self._cell_budget_exhausted = True

    def stats(self):
        """Fresh JSON-serialisable snapshot; counters satisfy
        policy_calls = complete_route + complete_no_route + complete_zero_hop
                       + incomplete_call_budget + skipped_after_cell_budget."""
        completed = self._complete_route + self._complete_no_route + self._complete_zero_hop
        calls = self._policy_calls
        return {
            "policy_identity": self.name,
            "search_identity": SEARCH_IDENTITY,
            "objective": OBJECTIVE,
            "algorithm": "iterative-deepening full enumeration of admissible simple paths per policy call; "
                         "no BFS, no distance pruning, no cache across calls; independently specified, "
                         "not the paper's brute force",
            "budget_scope": "independent safety controls; NOT paper settings",
            "incomplete_rule": "an incomplete or skipped call returns None (the packet waits); "
                               "never a route from partial work; never a fallback router",
            "max_call_expansions": self._max_call_expansions,
            "max_cell_expansions": self._max_cell_expansions,
            "policy_calls": calls,
            "complete_route": self._complete_route,
            "complete_no_route": self._complete_no_route,
            "complete_zero_hop": self._complete_zero_hop,
            "incomplete_call_budget": self._incomplete_call_budget,
            "skipped_after_cell_budget": self._skipped_after_cell_budget,
            "total_expansions": self._total_expansions,
            "complete_expansions_sum": self._complete_expansions_sum,
            "complete_expansions_max": self._complete_expansions_max,
            "incomplete_expansions_sum": self._incomplete_expansions_sum,
            # max_depth_completed: deepest level finished by ANY call, incomplete calls
            # included (see the module docstring); zero-hop calls give 0; diagnostic only.
            "max_depth_completed": self._max_depth_completed,
            "completeness_share": completed / calls if calls else None,
            "cell_budget_exhausted": self._cell_budget_exhausted,
        }
