"""Independently written reconstruction policies; no upstream source port."""
# Router interface: name; choose(packet, context) -> Decision | None; stats() -> dict.
# Simulator._schedule calls choose() at most once per tick for the head packet of a node that is still free
# when its turn comes (a node that became the receiver of another transfer earlier in the same tick is skipped).
# None means "no decision now": the packet stays at the head of its queue and is asked again at the next
# later tick on which its node is free.
# TBR_style_hop_oracle (HopOracle) is an exact unweighted BFS hop oracle, not brute-force enumeration.
# Optional TBR policies: TBR_bounded_exhaustive_reference (tbr_policy.py, using the search in tbr_reference.py)
# and TBR_enumeration (tbr_enum.py); none is in POLICY_NAMES.
# Units: time in ticks (tick_s = 0.1 s in the SimulationConfig defaults); distance in km;
# size in bytes; rate in bytes/s; TSR edge cost in seconds.
from collections import deque
from dataclasses import asdict, dataclass
import heapq
import math
from time import perf_counter
import numpy as np
from .config import ModelConfig, canonical_json, integer
from .features import delay_features, validate_adjacency, validate_ranges

# The four routers of the main series. Optional policies are not listed here: they are registered
# outside this file (single-run registration and plan options).
POLICY_NAMES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")


# neighbor: next node, exact int in 0..N-1. not_before_tick: departure tick, exact int, >= the current tick.
# Simulator._schedule: not_before_tick == tick -> the transfer starts if neighbor is in permitted_neighbors,
# otherwise the packet waits; > tick -> the packet waits ("scheduled_future_contact") and is asked again
# at the next later tick on which its node is free; an invalid neighbor or a non-int or past not_before_tick raises ValueError (the run stops).
@dataclass(frozen=True)
class Decision:
    neighbor: int
    not_before_tick: int


# Built by Simulator._schedule for each choose() call. adjacency and ranges_km are the arrays of THIS tick,
# shared by all calls of the tick: do not modify them. adjacency: binary N x N, symmetric, zero diagonal;
# ranges_km: N x N finite nonnegative distances in km. permitted_neighbors: ascending ints; each is adjacent
# now, not busy (not an end of an active transfer) and has buffer room (used + reserved + size <= buffer_bytes).
# cfg: the SimulationConfig of the run.
@dataclass(frozen=True)
class RoutingContext:
    tick: int
    adjacency: np.ndarray
    ranges_km: np.ndarray
    permitted_neighbors: tuple[int, ...]
    cfg: object


class HopOracle:
    """Exact unweighted BFS hop oracle (BASELINE behaviour) with a one-topology BFS cache.

    T055 OPT-4 (DESIGN T048 Q5 O-4). Equality note: the BASELINE `choose` reads only
    context.adjacency, packet.destination, context.permitted_neighbors and context.tick;
    it has no counter, no stored state and no argument validation beyond what indexing
    raises. The BFS distance list is a pure function of (adjacency content, destination),
    because BFS distances are unique. The cache keeps the distance lists of the MOST RECENT
    topology only, keyed by a private COPY of the adjacency (exact type np.ndarray, 2-D,
    dtype kind b/i/u/f; shape, dtype and every element compared, never a hash; in-place
    mutation by the caller is detected by the content comparison) and by the destination
    (exact int). Anything else (other array types or dtypes, non-int destinations, or a
    BFS that raises) runs the BASELINE computation uncached and stores nothing. The
    decision is always computed per call from the distance list and the per-call
    permitted_neighbors, exactly as in the BASELINE. Cached lists are never mutated.
    Decision rule: among the permitted neighbours from which the destination is reachable in the
    current graph, choose the one with the smallest BFS hop distance to the destination; ties go to
    the smaller node id; None when there is none. packet.visited and packet.location are not read, so
    the packet may step back or into a dead end: the chosen neighbour need not be closer to the
    destination than the current node.
    """
    name = "TBR_style_hop_oracle"

    def __init__(self):
        self._topology = None   # private copy of the most recent cached adjacency
        self._distances = {}    # exact int destination -> BFS distance list for _topology

    def _bfs(self, adjacency, packet):
        # BASELINE computation, statement for statement: one exact unweighted BFS.
        # Distances are measured FROM the destination (valid because the graph is undirected); -1 = unreachable.
        # Every popped node scans its whole adjacency row with np.flatnonzero, so one BFS costs O(N^2).
        distances = [-1] * len(adjacency)
        distances[packet.destination] = 0
        queue = deque([packet.destination])
        while queue:
            node = queue.popleft()
            for neighbor in np.flatnonzero(adjacency[node]):
                neighbor = int(neighbor)
                if distances[neighbor] < 0:
                    distances[neighbor] = distances[node] + 1
                    queue.append(neighbor)
        return distances

    def _distance_list(self, adjacency, packet):
        # Cache: only the most recent topology is kept; every cached lookup compares the whole N x N matrix
        # with the stored copy (np.array_equal, O(N^2)). A destination that is not exactly int (for example a
        # NumPy integer) or an adjacency that is not a 2-D np.ndarray of dtype kind b, i, u or f runs the plain
        # BFS and stores nothing; an array of another such dtype (or shape) replaces the cached topology.
        if not (type(adjacency) is np.ndarray and adjacency.ndim == 2 and adjacency.dtype.kind in "biuf"):
            return self._bfs(adjacency, packet)
        destination = packet.destination
        if type(destination) is not int:
            return self._bfs(adjacency, packet)
        stored = self._topology
        if (stored is not None and stored.shape == adjacency.shape and stored.dtype == adjacency.dtype
                and np.array_equal(stored, adjacency)):
            cached = self._distances.get(destination)
            if cached is not None:
                return cached
        else:
            self._topology = adjacency.copy()
            self._distances = {}
        distances = self._bfs(adjacency, packet)  # raises exactly as the BASELINE; nothing stored then
        self._distances[destination] = distances
        return distances

    def choose(self, packet, context):
        # One exact unweighted BFS per distinct (topology, destination); NOT brute-force enumeration.
        # permitted_neighbors is already filtered by the simulator (busy / no buffer room), so the best
        # neighbour may be missing from it, and then a neighbour with a larger BFS distance is chosen.
        distances = self._distance_list(context.adjacency, packet)
        candidates = [v for v in context.permitted_neighbors if distances[v] >= 0]
        if not candidates:
            return None
        chosen = min(candidates, key=lambda v: (distances[v], v))
        return Decision(chosen, context.tick)

    def stats(self):
        # Fig.5 is a figure of the paper (not shipped here); our BFS time is not comparable with its brute-force time.
        return {"algorithm": "exact unweighted BFS per hop; Fig.5 brute-force timing NON-COMPARABLE"}


class GLR:
    """Learned-score router (GLR): picks the permitted, not yet visited neighbour with the smallest score.

    Cache: ONE entry, keyed by (adjacency bytes, model config JSON), plus the ranges bytes in the
    optional delay mode. One score matrix [destination, candidate] serves all destinations and is
    replaced whenever the key changes. Candidates exclude packet.visited; when none is left,
    choose() returns None and the packet waits (no fallback route).
    """
    name = "GLR"

    def __init__(self, predictor, n, model_config=None):
        # Predictor contract (by feature mode; fixed immutable model/config):
        #   topology-only modes (default, paper-faithful): predictor(A, None)
        #   optional delay extension (not in the paper):    predictor(A, ranges_km)
        # Replacing weights/predictor requires a NEW GLR instance, never cache reuse.
        self.predictor = predictor
        self.n = n
        self.model_config = model_config if model_config is not None else ModelConfig()
        self.model_config.validate()
        self._key = None
        self._scores = None
        self.inference_count = 0
        self.inference_seconds = 0.0
        self.cache_hits = 0

    def choose(self, packet, context):
        adjacency = validate_adjacency(context.adjacency)
        if adjacency.shape != (self.n, self.n):
            raise ValueError("GLR fixed-N adjacency mismatch")
        candidates = [v for v in context.permitted_neighbors if v not in packet.visited]
        if not candidates:
            return None
        # Cost note: validate() and canonical_json(asdict(...)) run on every call that has candidates,
        # also on cache hits.
        self.model_config.validate()
        config_json = canonical_json(asdict(self.model_config))
        if self.model_config.uses_delay:
            # OPTIONAL delay extension: ranges are a predictor input, so they are
            # validated and keyed (all float64 km; conservative misses include
            # masked-out changes). Same physical guard as model inference, also on a hit.
            ranges = validate_ranges(context.ranges_km, self.n)
            # delay_features is called only for its validation; the returned array is not used.
            delay_features(adjacency, ranges, self.model_config)
            key = (adjacency.tobytes(), ranges.tobytes(), config_json)
        else:
            # Topology-only (default): the predictor input is binary A (Q derived from A).
            # Ranges are NOT an input, so they are neither validated nor part of the key.
            ranges = None
            key = (adjacency.tobytes(), config_json)
        # Availability/packet state are NOT predictor inputs in either mode.
        if key != self._key:
            started = perf_counter()
            scores = np.asarray(self.predictor(adjacency.copy(), None if ranges is None else ranges.copy()),
                                dtype=float)
            self.inference_seconds += perf_counter() - started
            if scores.shape != (self.n, self.n) or not np.isfinite(scores).all():
                raise ValueError("GLR predictor must return finite [destination,candidate] scores")
            self.inference_count += 1
            self._key, self._scores = key, scores.copy()
        else:
            self.cache_hits += 1
        # Finite negative scores allowed; no zero-score unreachable sentinel.
        # Smaller score = better: the neighbour with the smallest (score[destination, v], v) is chosen.
        neighbor = min(candidates, key=lambda v: (self._scores[packet.destination, v], v))
        return Decision(neighbor, context.tick)

    def stats(self):
        if self.model_config.uses_delay:
            boundary = ("one last binary A + all float64 km ranges + complete model config (optional delay "
                        "extension); fixed predictor/weights per instance; only with unvisited permitted candidates")
        else:
            boundary = ("one last binary A + complete model config (topology-only; ranges are not a predictor "
                        "input and do not enter the key); fixed predictor/weights per instance; only with "
                        "unvisited permitted candidates; cache hits amortize inference across ticks with unchanged A")
        return {"inference_count": self.inference_count, "inference_seconds": self.inference_seconds,
                "inference_seconds_per_call": self.inference_seconds / self.inference_count if self.inference_count else None,
                "cache_hits": self.cache_hits, "feature_spec": self.model_config.feature_spec,
                "feature_role": self.model_config.feature_role,
                "cache_boundary": boundary,
                "unreachable_behavior": "no reachability oracle; no candidate waits, including all-neighbors-visited"}


def source_dijkstra(source, destination, size_bytes, context):
    """Cheapest path from source to destination, with cost in SECONDS, on the graph of the calling tick.

    Edge weight = size_bytes / cfg.rate_bytes_s + range in km / cfg.light_speed_km_s (seconds, not ticks).
    Busy nodes, queues and buffers are ignored. Neighbours are scanned in ascending id; a predecessor
    changes only on a strict improvement; the heap order is (cost, node), so on equal cost the smaller
    node is popped first. The search stops when the destination is popped. Returns the list
    [source, ..., destination], or [] when the destination is unreachable.
    """
    n = len(context.adjacency)
    labels = [math.inf] * n
    labels[source] = 0.0
    predecessor = {}
    heap = [(0.0, source)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost != labels[node]:
            continue
        if node == destination:
            path = [node]
            while node != source:
                node = predecessor[node]
                path.append(node)
            return list(reversed(path))
        for neighbor in np.flatnonzero(context.adjacency[node]):
            neighbor = int(neighbor)
            weight = (size_bytes / context.cfg.rate_bytes_s
                      + context.ranges_km[node, neighbor] / context.cfg.light_speed_km_s)
            candidate = cost + weight
            if candidate < labels[neighbor]:
                labels[neighbor] = candidate
                predecessor[neighbor] = node
                heapq.heappush(heap, (candidate, neighbor))
    return []


class SourceDijkstra:
    """Source routing: the whole path is computed once per packet and stored in packet.header.

    The header is built at the FIRST choose() call for the packet (when it is first the head of the
    source queue and its node is free, not at creation), from the graph of that tick. The header is
    stored in the simulator-owned Packet (written to the result packets as source_header) and is never
    repaired. If the next hop is not permitted, choose() returns None and the packet waits (until its TTL
    at the latest). The queue is strict FIFO, so a blocked head also holds back the packets behind it.
    """
    name = "TSR_source_dijkstra"

    def __init__(self):
        self.source_searches = 0

    def choose(self, packet, context):
        if packet.header is None:
            if packet.location != packet.source:
                raise ValueError("source header missing after forwarding")
            packet.header = source_dijkstra(packet.source, packet.destination, packet.size_bytes, context)
            self.source_searches += 1
        if not packet.header:
            return None  # source initially unreachable: keep empty header, never repair
        # The two ValueError branches (here and above) signal an internal inconsistency; the simulator does not
        # catch them, so the run stops.
        if packet.hops >= len(packet.header) or packet.header[packet.hops] != packet.location:
            raise ValueError("source header/location mismatch")
        # Defensive branch: by reading of Simulator._complete, a packet that reaches the destination is closed
        # as delivered before it is asked again, so this return is not expected to be reached.
        if packet.hops + 1 >= len(packet.header):
            return None
        neighbor = packet.header[packet.hops + 1]
        if neighbor not in context.permitted_neighbors:
            return None  # absent, busy or buffer-blocked edge waits until TTL
        return Decision(neighbor, context.tick)

    def stats(self):
        # Descriptive text only; no time is measured here.
        return {"source_searches": self.source_searches, "repair": "none",
                "source_search_time": "first route call at source; geometric weights, no future queues"}


class ContactRouting:
    """Contact-plan router (CGR): asks the ContactPlan for the earliest-arrival first hop.

    Reads only the packet fields location, destination, expiry_tick and size_bytes, plus context.tick
    and context.cfg; permitted_neighbors, packet.visited, queues and random failures are not read.
    (The identity of the packet object is also used, as the key of _none_memo.)
    The departure in the answer may lie in the future; every call recomputes the route, except that a
    remembered None answer may be reused (see _none_memo).
    """
    name = "CGR_contact_plan"

    def __init__(self, plan):
        self.plan = plan
        self.plan_queries = 0
        # T054 OPT-3 (DESIGN T048 Q5 O-2, NEGATIVE results only): id(packet) ->
        # [packet, cfg, plan, {(location, destination, expiry_tick, size_bytes): first None tick}].
        # The packet object is held, so its id cannot be reused while the entry exists.
        # No eviction: one entry per packet that ever reaches choose() (created before the search); each entry
        # keeps its packet alive; the inner dict gets a key only after a None answer.
        self._none_memo = {}

    def choose(self, packet, context):
        self.plan_queries += 1  # counted per call, also on a memo hit (as in BASELINE)
        # Equality note: earliest_hop is exact (time-dependent Dijkstra, FIFO edges), so
        # None means no feasible path with departures >= now. Any path feasible from a
        # later tick t' >= t is also feasible from t, hence None at t implies None at
        # every t' >= t for the same (location, destination, expiry, size, cfg, plan).
        # Positive results are never reused (not granted). On a hit the tick is still
        # validated like earliest_hop does; location/destination/deadline were validated
        # by the earlier completed call with the same key.
        key = (packet.location, packet.destination, packet.expiry_tick, packet.size_bytes)
        entry = self._none_memo.get(id(packet))
        if entry is not None and (entry[0] is not packet or entry[1] is not context.cfg
                                  or entry[2] is not self.plan):
            entry = None
        if entry is None:
            entry = [packet, context.cfg, self.plan, {}]
            self._none_memo[id(packet)] = entry
        known = entry[3].get(key)
        if known is not None:
            integer(context.tick, "now_tick", 0)
            if context.tick >= known:
                return None
        route = self.plan.earliest_hop(packet.location, packet.destination, context.tick,
                                       packet.expiry_tick, packet.size_bytes, context.cfg)
        if route is None:
            if known is None or context.tick < known:
                entry[3][key] = context.tick
            return None
        # First hop can be a future contact. Engine never sends before it.
        # Current/future queues and random failures NOT forecast by the plan.
        # A future departure (not_before_tick > tick) makes the simulator keep the packet at its queue head with
        # last_wait "scheduled_future_contact"; it is asked again at every later tick on which its node is free, and this method
        # recomputes the route with the new tick. Positive answers are never stored; only None answers are.
        return Decision(route.neighbor, route.departure_tick)

    def stats(self):
        # "replanning": earliest_hop runs on every call except when the memo already answers None for the
        # same key; plan_queries counts calls, not searches.
        return {"plan_queries": self.plan_queries, "contact_plan": self.plan.metadata(),
                "replanning": "each route call, remaining TTL bounded by observation horizon",
                "knowledge": "scheduled geometry only; no future queues or random failures"}
