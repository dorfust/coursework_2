"""Scheduled geometric contacts on an explicit right-continuous tick grid."""
from dataclasses import dataclass
import heapq
import math
import numpy as np
from .config import content_hash, integer
from .geometry import graph_from_positions, make_trajectory
from .sim_config import service_ticks


class GeometryNetwork:
    """One shared range/LOS predicate, with only the most recent snapshot cached."""
    def __init__(self, cfg):
        self.cfg = cfg.validate()
        self.trajectory = make_trajectory(cfg.orbit, cfg.phase_seed)
        self._tick = None
        self._snapshot = None
        self.snapshot_builds = 0

    def snapshot(self, tick):
        integer(tick, "tick", 0)
        if tick != self._tick:
            positions = self.trajectory.positions_km(tick * self.cfg.tick_s)
            self._snapshot = graph_from_positions(positions, self.cfg.orbit)
            self._tick = tick
            self.snapshot_builds += 1
        return self._snapshot


@dataclass(frozen=True)
class Contact:
    start_tick: int
    end_tick: int  # exclusive cell end; completion exactly at this boundary allowed


@dataclass(frozen=True)
class PlannedHop:
    neighbor: int
    departure_tick: int
    arrival_tick: int  # final destination arrival, not just next-hop finish


class ContactPlan:
    """Intervals keyed by unordered edge; caller supplies geometric start distance.

    earliest_hop is a time-dependent Dijkstra with WAITING CLOSURE on every
    edge: it minimizes over all feasible departure ticks in future contacts.
    It is not Dijkstra on the current-neighbor graph. The waiting closure is
    FIFO even if tick-rounded service duration changes with departure time.
    """
    def __init__(self, n, horizon_tick, intervals, distance_at):
        integer(n, "n", 2)
        integer(horizon_tick, "horizon_tick")
        self.n = n
        self.horizon_tick = horizon_tick
        self.distance_at = distance_at
        self.intervals = {}
        self.neighbors = [[] for _ in range(n)]
        for edge, contacts in sorted(intervals.items()):
            if len(edge) != 2:
                raise ValueError("contact edge must have two IDs")
            u, v = edge
            integer(u, "contact u", 0)
            integer(v, "contact v", 0)
            if not 0 <= u < v < n:
                raise ValueError("contact edges must be canonical unordered IDs")
            previous_end = -1
            values = []
            for contact in contacts:
                integer(contact.start_tick, "contact start", 0)
                integer(contact.end_tick, "contact end")
                if not previous_end <= contact.start_tick < contact.end_tick <= horizon_tick:
                    raise ValueError("contact intervals must be ordered, disjoint, within horizon")
                values.append(contact)
                previous_end = contact.end_tick
            if values:
                self.intervals[(u, v)] = tuple(values)
                self.neighbors[u].append(v)
                self.neighbors[v].append(u)
        for values in self.neighbors:
            values.sort()

    def metadata(self):
        rows = [{"edge": list(edge), "cells": [[c.start_tick, c.end_tick] for c in values]}
                for edge, values in sorted(self.intervals.items())]
        return {"schema": "ssn-contact-grid-v1", "n": self.n,
                "horizon_tick": self.horizon_tick, "interval_count": sum(len(v) for v in self.intervals.values()),
                "interval_sha256": content_hash(rows),
                "semantics": "true sample at k holds on [k*dt,(k+1)*dt); ends allow completion"}

    def _edge_arrival(self, u, v, earliest, deadline, size_bytes, cfg, limit=math.inf):
        """Minimal (arrival, departure) over feasible departures >= earliest, or None.

        Result is the lexicographic minimum (arrival, departure) among departures
        with arrival <= min(contact end, deadline); with the optional `limit`
        (default: no limit) only arrivals strictly below `limit` are accepted,
        otherwise None. With the default limit the result equals the BASELINE
        b6f5f516 function (tests/reference/contacts_ref.py).

        T054 equality notes (DESIGN T048 Q5 O-1, O-1b), departures are scanned in
        strictly increasing order over all contacts (ordered, disjoint), so an
        equal arrival from a later departure never replaces `best`.
        s_min = service_ticks(..., distance 0.0, ...) >= 1 is computed by the same
        function; service_ticks is a composition of monotone nondecreasing IEEE-754
        operations in the distance, hence duration >= s_min for every finite
        distance >= 0. A departure d can only reach arrival >= d + s_min, so:
        (i) d > stop - s_min fails `arrival <= stop`; (ii) d + s_min >= cap, where
        cap = best arrival or `limit`, cannot yield an accepted improvement; later
        departures and later contacts start no earlier, so `break` is exact.
        s_min is computed lazily at the first non-empty scan range, the first
        place where the BASELINE code calls service_ticks, so d-independent
        argument errors surface at the same call. The only difference to the
        BASELINE: distance_at / service_ticks are not evaluated at skipped
        departures, so invalid (negative or non-finite) distances there no longer raise.
        """
        best = None
        s_min = None
        for contact in self.intervals.get((min(u, v), max(u, v)), ()):
            start = max(earliest, contact.start_tick)
            stop = min(contact.end_tick, deadline)
            if start >= stop:
                continue
            if s_min is None:
                s_min = service_ticks(size_bytes, cfg.rate_bytes_s, 0.0,
                                      cfg.light_speed_km_s, cfg.tick_s)
            if start + s_min >= (best[0] if best is not None else limit):
                break  # no departure of this or any later contact can improve
            for departure in range(start, stop - s_min + 1):
                if departure + s_min >= (best[0] if best is not None else limit):
                    break  # no later departure can improve either
                duration = service_ticks(size_bytes, cfg.rate_bytes_s,
                                         self.distance_at(departure, u, v),
                                         cfg.light_speed_km_s, cfg.tick_s)
                arrival = departure + duration
                if arrival <= stop and arrival < limit and (best is None or (arrival, departure) < best):
                    best = (arrival, departure)
        return best

    def earliest_hop(self, source, destination, now_tick, deadline_tick, size_bytes, cfg):
        # T054 OPT-2 (DESIGN T048 Q5 O-1b): the BASELINE relaxes every neighbour and
        # discards the result unless next_arrival < labels[neighbor]. Passing
        # limit = labels[neighbor] makes _edge_arrival return exactly the tuples that
        # pass that strict test (and None otherwise); the update test below is kept.
        if not 0 <= source < self.n or not 0 <= destination < self.n:
            raise ValueError("contact query endpoint out of range")
        integer(now_tick, "now_tick", 0)
        integer(deadline_tick, "deadline_tick", 0)
        if cfg.orbit.n != self.n:
            raise ValueError("contact/config N mismatch")
        deadline = min(deadline_tick, self.horizon_tick)
        if source == destination or now_tick >= deadline:
            return None
        labels = [math.inf] * self.n
        labels[source] = now_tick
        first = {}
        heap = [(now_tick, source)]
        while heap:
            arrival, node = heapq.heappop(heap)
            if arrival != labels[node]:
                continue
            if node == destination:
                neighbor, departure = first[node]
                return PlannedHop(neighbor, departure, arrival)
            for neighbor in self.neighbors[node]:
                result = self._edge_arrival(node, neighbor, arrival, deadline, size_bytes, cfg,
                                            labels[neighbor])
                if result is None:
                    continue
                next_arrival, departure = result
                if next_arrival < labels[neighbor]:
                    labels[neighbor] = next_arrival
                    first[neighbor] = (neighbor, departure) if node == source else first[node]
                    heapq.heappush(heap, (next_arrival, neighbor))
        return None


def build_geometric_plan(cfg):
    """Stream graphs into intervals; retain positions only, never an H*N*N cube."""
    cfg.validate()
    trajectory = make_trajectory(cfg.orbit, cfg.phase_seed)
    # Position memory O(H*N); graph working memory O(N*N); contacts O(intervals).
    positions = np.empty((cfg.horizon_tick, cfg.orbit.n, 3), dtype=np.float64)
    intervals = {}
    opened = {}
    for tick in range(cfg.horizon_tick):
        positions[tick] = trajectory.positions_km(tick * cfg.tick_s)
        adjacency, _ = graph_from_positions(positions[tick], cfg.orbit)
        current = set(zip(*np.nonzero(np.triu(adjacency, 1))))
        current = {(int(u), int(v)) for u, v in current}
        for edge in sorted(set(opened) - current):
            intervals.setdefault(edge, []).append(Contact(opened.pop(edge), tick))
        for edge in sorted(current - set(opened)):
            opened[edge] = tick
    for edge, start in sorted(opened.items()):
        intervals.setdefault(edge, []).append(Contact(start, cfg.horizon_tick))

    def distance_at(tick, u, v):
        return float(np.linalg.norm(positions[tick, u] - positions[tick, v]))

    return ContactPlan(cfg.orbit.n, cfg.horizon_tick, intervals, distance_at)
