"""Bounded exhaustive reference, independently specified; NOT author TBR code.

No policy registration, runtime measurement, BFS fallback or shortest-path pruning.
See TBR_REFERENCE_SPEC.md for admissibility and the exact expansion boundary.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from numbers import Integral
from typing import Literal

import numpy as np

from .features import validate_adjacency

SEARCH_IDENTITY = "bounded_exhaustive_simple_paths_v1"
OBJECTIVE = "min_edges_then_lexicographic_full_path"
DEFAULT_MAX_NODES = 12
DEFAULT_MAX_EXPANSIONS = 100000


@dataclass(frozen=True)
class TBRReferenceResult:
    """An exhaustive conclusion, never a partial route or incomplete no-route."""

    status: Literal["route", "no_route"]
    path: tuple[int, ...] | None
    edge_count: int | None
    expansions: int
    complete_paths: int
    complete: bool = field(default=True, init=False)
    search_identity: str = field(default=SEARCH_IDENTITY, init=False)
    objective: str = field(default=OBJECTIVE, init=False)


@dataclass(frozen=True)
class TBRIncompleteDetails:
    """Diagnostics only: deliberately contains no best-so-far path/objective."""

    reason: Literal["max_nodes", "max_expansions"]
    node_count: int
    max_nodes: int
    max_expansions: int
    expansions: int
    complete: bool = field(default=False, init=False)
    search_identity: str = field(default=SEARCH_IDENTITY, init=False)


class TBRSearchIncomplete(RuntimeError):
    """Safety bound prevented a complete conclusion; must propagate to callers."""

    def __init__(self, details: TBRIncompleteDetails):
        self.details = details
        super().__init__(
            f"{details.search_identity}: incomplete ({details.reason}); "
            f"nodes={details.node_count}, expansions={details.expansions}, "
            f"max_nodes={details.max_nodes}, max_expansions={details.max_expansions}"
        )


def _integer(value: int, name: str) -> int:
    # Includes NumPy integer scalars, but excludes both Python/NumPy booleans.
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer, not bool")
    return int(value)


def _node_id(value: int, n: int, name: str) -> int:
    node = _integer(value, name)
    if not 0 <= node < n:
        raise ValueError(f"{name} must satisfy 0 <= ID < {n}")
    return node


def _id_set(values: Iterable[int], n: int, name: str) -> frozenset[int]:
    # These masks are explicit ID collections, NOT binary node-mask vectors.
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError(f"{name} must be an iterable of distinct node IDs")
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError(f"{name} must be an iterable of distinct node IDs") from error
    nodes: set[int] = set()
    for value in iterator:
        node = _node_id(value, n, name)
        if node in nodes:
            raise ValueError(f"{name} must contain distinct node IDs")
        nodes.add(node)
    # Valid IDs plus duplicate rejection bound consumption to at most n+1 items.
    return frozenset(nodes)


def exhaustive_simple_path_reference(
    adjacency,
    source: int,
    destination: int,
    *,
    permitted_first_hops: Iterable[int],
    visited: Iterable[int] = (),
    max_nodes: int = DEFAULT_MAX_NODES,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> TBRReferenceResult:
    """Enumerate ALL admissible simple paths, then select by (edges, full path).

    Adjacency follows features.validate_adjacency (undirected binary N>=2).
    First-hop IDs must actually neighbor source; visited may include source.
    All validation and the node bound apply even for source == destination.
    One expansion enters one prefix, including root, dead ends and destinations.
    If another prefix remains after max_expansions entries, raise incomplete.
    Exactly max_expansions entries suffice when no prefix remains.
    """
    array = validate_adjacency(adjacency)
    n = len(array)
    source = _node_id(source, n, "source")
    destination = _node_id(destination, n, "destination")
    permitted = _id_set(permitted_first_hops, n, "permitted_first_hops")
    excluded = _id_set(visited, n, "visited")
    max_nodes = _integer(max_nodes, "max_nodes")
    max_expansions = _integer(max_expansions, "max_expansions")
    if max_nodes <= 0 or max_expansions <= 0:
        raise ValueError("max_nodes and max_expansions must be positive integers")
    for neighbor in permitted:
        if neighbor == source or not array[source, neighbor]:
            raise ValueError("permitted_first_hops must be actual neighbors of source")

    def incomplete(reason: Literal["max_nodes", "max_expansions"], expansions: int):
        return TBRSearchIncomplete(TBRIncompleteDetails(
            reason=reason, node_count=n, max_nodes=max_nodes,
            max_expansions=max_expansions, expansions=expansions,
        ))

    if n > max_nodes:
        raise incomplete("max_nodes", 0)

    # Snapshot only after the node guard. No mutation of caller arrays/masks.
    neighbors = tuple(tuple(int(v) for v in np.flatnonzero(row)) for row in array)
    first_hops = permitted - excluded
    blocked = excluded - {source}
    # LIFO, reversed insertion => depth-first lexicographic prefix entry order.
    # No recursion, distance computation, early optimal-route return or pruning.
    stack: list[tuple[int, ...]] = [(source,)]
    expansions = 0
    complete_paths = 0
    best_path: tuple[int, ...] | None = None
    while stack:
        if expansions == max_expansions:
            raise incomplete("max_expansions", expansions)
        path = stack.pop()
        expansions += 1
        current = path[-1]
        if current == destination:
            complete_paths += 1
            if best_path is None or (len(path), path) < (len(best_path), best_path):
                best_path = path
            continue  # destination is terminal, including the zero-edge root
        for neighbor in reversed(neighbors[current]):
            if neighbor in blocked or neighbor in path:
                continue
            if len(path) == 1 and neighbor not in first_hops:
                continue
            stack.append(path + (neighbor,))

    if best_path is None:
        return TBRReferenceResult("no_route", None, None, expansions, complete_paths)
    return TBRReferenceResult("route", best_path, len(best_path) - 1,
                              expansions, complete_paths)
