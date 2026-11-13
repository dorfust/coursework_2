"""Isolated native Decision adapter; independently specified, NOT author TBR.

Accepted dependency: tbr_reference.py at 6df242596c554bb50c04a01eab9599cc54f4c52a.
No registration, cache, packet header, BFS fallback, timing or simulator changes.
See TBR_NATIVE_ADAPTER.md for counter definitions and integration boundaries.
"""
# Adapter: runs exhaustive_simple_path_reference on every choose call and turns its path into
# Decision(path[1], tick); see tbr_reference.py. The document name and the commit hash in the docstring
# are references only: this module does not import or read them.
from numbers import Integral

import numpy as np

from .policies import Decision
from .tbr_reference import (
    DEFAULT_MAX_EXPANSIONS,
    DEFAULT_MAX_NODES,
    OBJECTIVE,
    SEARCH_IDENTITY,
    TBRSearchIncomplete,
    exhaustive_simple_path_reference,
)


def _positive_budget(value: int, name: str) -> int:
    # Match the accepted core: NumPy integers allowed; bool is not a budget.
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be a positive integer, not bool")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


class TBR_bounded_exhaustive_reference:
    """A fresh exhaustive search per choose call, with diagnostic-only counters.

    Bounds are independent safety controls, not settings attributed to authors.
    Instances are intended for sequential use, as are the existing policies.
    """

    name = "TBR_bounded_exhaustive_reference"

    def __init__(
        self,
        *,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    ):
        self._max_nodes = _positive_budget(max_nodes, "max_nodes")
        self._max_expansions = _positive_budget(max_expansions, "max_expansions")
        self._policy_calls = 0
        self._completed_searches = 0
        self._complete_route_searches = 0
        self._complete_no_route_searches = 0
        self._complete_zero_hop_searches = 0
        self._incomplete_searches = 0
        self._incomplete_max_nodes_searches = 0
        self._incomplete_max_expansions_searches = 0
        self._invalid_input_calls = 0
        self._completed_prefix_entries = 0
        self._incomplete_prefix_entries = 0
        self._completed_destination_paths = 0

    @property
    def max_nodes(self) -> int:
        return self._max_nodes

    @property
    def max_expansions(self) -> int:
        return self._max_expansions

    def choose(self, packet, context) -> Decision | None:
        self._policy_calls += 1
        try:
            # The search may start only with a first hop that is in permitted_neighbors and not in packet.visited;
            # visited nodes are also blocked on the whole path. HopOracle in policies.py does not read packet.visited.
            result = exhaustive_simple_path_reference(
                context.adjacency,
                packet.location,
                packet.destination,
                permitted_first_hops=context.permitted_neighbors,
                visited=packet.visited,
                max_nodes=self._max_nodes,
                max_expansions=self._max_expansions,
            )
        except TBRSearchIncomplete as error:
            self._incomplete_searches += 1
            self._incomplete_prefix_entries += error.details.expansions
            if error.details.reason == "max_nodes":
                self._incomplete_max_nodes_searches += 1
            else:  # Accepted core's only other structured reason: max_expansions.
                self._incomplete_max_expansions_searches += 1
            # TBRSearchIncomplete is re-raised: Simulator._schedule does not catch exceptions from choose(), so the
            # run stops. It is never converted into a route, a drop or a fallback.
            raise  # Preserve this exact exception and details; never a route/drop.
        except ValueError:
            self._invalid_input_calls += 1
            raise  # Invalid inputs are ordinary errors, NOT complete no-route.

        self._completed_searches += 1
        self._completed_prefix_entries += result.expansions
        self._completed_destination_paths += result.complete_paths
        if result.path is None:
            self._complete_no_route_searches += 1
            return None
        if len(result.path) == 1:
            self._complete_zero_hop_searches += 1
            return None  # Terminal zero-hop: do not forward to the current node.
        self._complete_route_searches += 1
        return Decision(result.path[1], context.tick)

    def stats(self) -> dict:
        """Return a fresh snapshot; prefix totals include typed incomplete work."""
        return {
            "policy_identity": self.name,
            "search_identity": SEARCH_IDENTITY,
            "objective": OBJECTIVE,
            "algorithm": "exhaustive admissible simple paths per policy call; independently specified, not author code or timing",
            "budget_scope": "independent safety controls; not author settings",
            "max_nodes": self._max_nodes,
            "max_expansions": self._max_expansions,
            "policy_calls": self._policy_calls,
            "completed_searches": self._completed_searches,
            "complete_route_searches": self._complete_route_searches,
            "complete_no_route_searches": self._complete_no_route_searches,
            "complete_zero_hop_searches": self._complete_zero_hop_searches,
            "incomplete_searches": self._incomplete_searches,
            "incomplete_max_nodes_searches": self._incomplete_max_nodes_searches,
            "incomplete_max_expansions_searches": self._incomplete_max_expansions_searches,
            "invalid_input_calls": self._invalid_input_calls,
            "completed_prefix_entries": self._completed_prefix_entries,
            "incomplete_prefix_entries": self._incomplete_prefix_entries,
            "total_prefix_entries": self._completed_prefix_entries + self._incomplete_prefix_entries,
            "completed_destination_paths": self._completed_destination_paths,
        }
