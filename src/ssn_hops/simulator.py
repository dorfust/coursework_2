"""Tick-quantized single-copy store-and-forward simulation (unexecuted here)."""
from collections import Counter
from dataclasses import dataclass, field
import heapq
from statistics import mean, median
from time import perf_counter
import numpy as np
from .contacts import GeometryNetwork
from .policies import RoutingContext
from .sim_config import service_ticks
from .traffic import edge_tick_failure, validate_records

# T056 OPT-6: the class whose instances the Simulator builds itself when no network is supplied.
# Bound at import time; a network of any other type (also a patched replacement of the module
# name GeometryNetwork) is always validated per tick.
_SELF_BUILT_NETWORK_TYPE = GeometryNetwork


@dataclass
class Packet:
    # Field notes (this file only). status: "scheduled" (before injection), then "pending" once admitted
    # (it stays "pending" while a transfer is active), then "delivered" or "failed"; a rejected injection
    # goes straight to "failed"; "in_transition" exists only inside _complete. expiry_tick = created_tick + cfg.ttl_ticks.
    packet_id: int
    created_tick: int
    source: int
    destination: int
    size_bytes: int
    expiry_tick: int
    # location is the node that holds the sender copy; it changes only when a hop completes (_complete).
    location: int
    status: str = "scheduled"
    admitted: bool = False
    terminal_tick: int | None = None
    terminal_reason: str | None = None
    # queued_tick is the local-receive FIFO key used by _schedule and audit(): created_tick at
    # construction, then the current tick at every completed hop.
    queued_tick: int = 0
    # visited starts as {source} and gains the receiver at every completed hop. hops counts COMPLETED hops
    # only. hop_failures counts the failed attempts on the current hop and is reset in _complete;
    # total_aborts is never reset.
    visited: set[int] = field(default_factory=set)
    hops: int = 0
    hop_failures: int = 0
    total_aborts: int = 0
    # header is neither read nor written in this file; it is only copied to the result rows as "source_header".
    # last_wait is the latest wait reason set in _schedule; it is reset to None when a transfer starts,
    # when a hop completes and when the packet becomes terminal.
    header: list[int] | None = None
    last_wait: str | None = None


@dataclass(frozen=True)
class Transfer:
    packet_id: int
    sender: int
    receiver: int
    start_tick: int
    finish_tick: int


# Units used in this file: time in ticks (events also carry time_s = tick * cfg.tick_s; delays are
# reported in seconds); distances (ranges) in km; sizes in bytes; rate in bytes per second
# (cfg.rate_bytes_s); goodput in bits per second.
class Simulator:
    # network must provide snapshot(tick) -> (adjacency, ranges_km); failure_sampler(seed, u, v, tick, p) -> bool.
    # Defaults: GeometryNetwork(cfg) and traffic.edge_tick_failure.
    def __init__(self, cfg, records, policy, network=None, failure_sampler=edge_tick_failure):
        self.cfg = cfg.validate()
        self.records = validate_records(records, cfg)
        self.policy = policy
        # T056 OPT-6: remember the network built here (None when the caller supplied one).
        self._own_network = GeometryNetwork(cfg) if network is None else None
        self.network = network if network is not None else self._own_network
        self.failure_sampler = failure_sampler
        self.packets = {r.packet_id: Packet(r.packet_id, r.created_tick, r.source, r.destination,
                                          r.size_bytes, r.created_tick + cfg.ttl_ticks, r.source,
                                          queued_tick=r.created_tick, visited={r.source})
                        for r in self.records}
        self.queues = [[] for _ in range(cfg.orbit.n)]
        self.used = [0] * cfg.orbit.n
        self.reserved = [0] * cfg.orbit.n
        self.busy = set()
        self.active = {}
        self.events = []
        self.terminal_ids = set()
        self.counts = Counter({key: 0 for key in (
            "admitted", "injection_rejected", "route_calls", "route_wait_calls",
            "future_contact_wait_calls", "blocked_decision_calls", "started_transfers",
            "aborted_transfers", "cancelled_transfers", "completed_hops", "completed_hop_bytes")})
        self.abort_reasons = Counter()
        self.route_seconds = 0.0
        self.topology_seconds = 0.0
        self.tick = 0
        self._ran = False

    # Event kinds used in this file: generated, admitted, transfer_started, transfer_aborted,
    # transfer_cancelled, hop_completed, terminal.
    def event(self, kind, packet, **details):
        self.events.append({"tick": self.tick, "time_s": self.tick * self.cfg.tick_s,
                            "kind": kind, "packet_id": packet.packet_id, **details})

    def _release_transfer(self, packet):
        transfer = self.active.pop(packet.packet_id)
        self.busy.remove(transfer.sender)
        self.busy.remove(transfer.receiver)
        self.reserved[transfer.receiver] -= packet.size_bytes
        return transfer

    def _remove_stored(self, packet):
        self.queues[packet.location].remove(packet.packet_id)
        self.used[packet.location] -= packet.size_bytes

    # A terminal transition of a packet with an active transfer cancels the transfer (counter cancelled_transfers,
    # event transfer_cancelled) and releases busy and reserved bytes; a stored (pending) packet is removed from
    # its queue. A second terminal transition of the same packet raises RuntimeError.
    def _terminal(self, packet, status, reason):
        if packet.packet_id in self.terminal_ids or packet.status in ("delivered", "failed"):
            raise RuntimeError("duplicate packet terminal transition")
        if packet.packet_id in self.active:
            transfer = self._release_transfer(packet)
            self.counts["cancelled_transfers"] += 1
            self.event("transfer_cancelled", packet, reason=reason, receiver=transfer.receiver)
        if packet.status == "pending":
            self._remove_stored(packet)
        packet.status = status
        packet.terminal_tick = self.tick
        packet.terminal_reason = reason
        packet.last_wait = None
        self.terminal_ids.add(packet.packet_id)
        self.event("terminal", packet, status=status, reason=reason)

    def _abort(self, packet, reason):
        transfer = self._release_transfer(packet)
        packet.hop_failures += 1
        packet.total_aborts += 1
        self.counts["aborted_transfers"] += 1
        self.abort_reasons[reason] += 1
        self.event("transfer_aborted", packet, sender=transfer.sender, receiver=transfer.receiver,
                   reason=reason, hop_failed_attempts=packet.hop_failures)
        if packet.hop_failures > self.cfg.additional_retries:
            self._terminal(packet, "failed", "retry_exhaustion")
        # Otherwise the same sender copy can restart, from byte zero, this tick.
        # The packet stays at the head of its sender's queue, so _schedule (same tick, unless this is the last
        # tick of the horizon) calls choose() again (if the sender is still free when its turn comes) and the
        # router may pick another neighbour.
        # hop_failures is reset only in _complete, so one hop gets at most 1 + additional_retries attempts
        # (e.g. 4 when additional_retries = 3), counted over every neighbour tried from this node.

    def _complete(self, packet):
        transfer = self._release_transfer(packet)
        self._remove_stored(packet)
        packet.location = transfer.receiver
        packet.hops += 1
        packet.hop_failures = 0
        packet.visited.add(packet.location)
        self.counts["completed_hops"] += 1
        self.counts["completed_hop_bytes"] += packet.size_bytes
        self.event("hop_completed", packet, sender=transfer.sender, receiver=transfer.receiver)
        # Temporarily not stored: terminal cannot remove a second sender copy.
        packet.status = "in_transition"
        # Delivery is checked first. Hop limit 2 * N (reason 'hop_limit'): a safety stop of this reconstruction;
        # no paper value is asserted, and it is not a configuration field. At the default TTL (3000 ticks, sim_config) and 15 ticks per hop (default packet
        # size and rate) a packet completes at most 200 hops, so for N > 100 the TTL ends a wandering packet
        # before this limit can; the limit can end a packet only if ttl_ticks >= 15 * 2N, i.e. for N <= 100 at the defaults.
        if packet.location == packet.destination:
            self._terminal(packet, "delivered", "delivered")
        elif packet.hops >= 2 * self.cfg.orbit.n:
            self._terminal(packet, "failed", "hop_limit")
        else:
            packet.status = "pending"
            packet.queued_tick = self.tick
            packet.last_wait = None
            self.queues[packet.location].append(packet.packet_id)
            self.used[packet.location] += packet.size_bytes

    def _inject(self, packet):
        self.event("generated", packet, source=packet.source, destination=packet.destination,
                   size_bytes=packet.size_bytes)
        if packet.size_bytes > self.cfg.buffer_bytes:
            self.counts["injection_rejected"] += 1
            self._terminal(packet, "failed", "packet_oversize")
        elif self.used[packet.source] + self.reserved[packet.source] + packet.size_bytes > self.cfg.buffer_bytes:
            self.counts["injection_rejected"] += 1
            self._terminal(packet, "failed", "injection_buffer")
        else:
            packet.status = "pending"
            packet.admitted = True
            self.counts["admitted"] += 1
            self.queues[packet.source].append(packet.packet_id)
            self.used[packet.source] += packet.size_bytes
            self.event("admitted", packet)

    def _schedule(self, adjacency, ranges):
        # Strict local-receive FIFO: only a node's head may attempt to send.
        # Contract with the router (policy.choose is called only here): every node with a non-empty queue that is
        # still free when its turn comes gets one choose() call per tick (a node that became busy earlier in this
        # loop is skipped), for its head packet only, in the order (head queued_tick,
        # packet_id, node); busy grows while the loop runs, so this order decides who gets a contested
        # neighbour. choose() is called even when permitted is empty. permitted = neighbours adjacent now
        # (ascending ids), not busy, with room for the packet (used + reserved + size <= buffer_bytes),
        # evaluated when that node is served. Answers: None, a future not_before_tick, or a neighbour not in
        # permitted all mean 'wait'; the same head is asked again at the next later tick that calls _schedule
        # and finds its node free.
        # An invalid neighbour, or a not_before_tick that is not an int or lies in the past, raises ValueError.
        # Otherwise the transfer starts now. Exceptions from choose() are not caught: they end Simulator.run.
        heads = [(self.packets[q[0]].queued_tick, q[0], node)
                 for node, q in enumerate(self.queues) if q and node not in self.busy]
        for _, packet_id, node in sorted(heads):
            if node in self.busy:
                continue
            packet = self.packets[packet_id]
            permitted = tuple(int(v) for v in np.flatnonzero(adjacency[node])
                              if int(v) not in self.busy
                              and self.used[int(v)] + self.reserved[int(v)] + packet.size_bytes <= self.cfg.buffer_bytes)
            context = RoutingContext(self.tick, adjacency, ranges, permitted, self.cfg)
            started = perf_counter()
            decision = self.policy.choose(packet, context)
            self.route_seconds += perf_counter() - started
            self.counts["route_calls"] += 1
            # last_wait strings (copied to the result rows; the counter is named in brackets):
            #   no_route_or_no_permitted_candidate [route_wait_calls]: choose() returned None; the simulator
            #     cannot tell 'no route' from 'no permitted candidate'.
            #   scheduled_future_contact [future_contact_wait_calls]: not_before_tick is later than this tick.
            #   geometric_or_contention_or_receiver_buffer [blocked_decision_calls]: the chosen neighbour is not
            #     in permitted, i.e. no edge now, or the neighbour is busy, or its buffer has no room; the three
            #     causes are not told apart in the output.
            if decision is None:
                packet.last_wait = "no_route_or_no_permitted_candidate"
                self.counts["route_wait_calls"] += 1
                continue
            if type(decision.neighbor) is not int or not 0 <= decision.neighbor < self.cfg.orbit.n:
                raise ValueError("policy returned invalid neighbor")
            if type(decision.not_before_tick) is not int or decision.not_before_tick < self.tick:
                raise ValueError("policy returned invalid departure tick")
            if decision.not_before_tick > self.tick:
                packet.last_wait = "scheduled_future_contact"
                self.counts["future_contact_wait_calls"] += 1
                continue
            if decision.neighbor not in permitted:
                packet.last_wait = "geometric_or_contention_or_receiver_buffer"
                self.counts["blocked_decision_calls"] += 1
                continue
            # duration = ceil((size/rate + distance/c)/dt) ticks for the distance at the START of the transfer;
            # finish_tick is fixed here. Later ticks re-check only that the edge still exists, not the distance.
            duration = service_ticks(packet.size_bytes, self.cfg.rate_bytes_s,
                                     float(ranges[node, decision.neighbor]),
                                     self.cfg.light_speed_km_s, self.cfg.tick_s)
            transfer = Transfer(packet_id, node, decision.neighbor, self.tick, self.tick + duration)
            self.active[packet_id] = transfer
            self.busy.update((node, decision.neighbor))
            self.reserved[decision.neighbor] += packet.size_bytes
            packet.last_wait = None
            self.counts["started_transfers"] += 1
            self.event("transfer_started", packet, sender=node, receiver=decision.neighbor,
                       finish_tick=transfer.finish_tick, hop_failed_attempts=packet.hop_failures)

    # Consistency checks of the byte accounting, queues, reservations, busy set and terminal ledger; raises
    # RuntimeError on a mismatch. Runs after every tick when cfg.audit_each_tick is true (default) and once
    # after the loop.
    def audit(self):
        stored = []
        for node, queue in enumerate(self.queues):
            stored.extend(queue)
            expected = sum(self.packets[pid].size_bytes for pid in queue)
            if expected != self.used[node]:
                raise RuntimeError("stored byte accounting mismatch")
            if not 0 <= self.used[node] + self.reserved[node] <= self.cfg.buffer_bytes:
                raise RuntimeError("buffer capacity invariant violated")
            if any(self.packets[pid].location != node or self.packets[pid].status != "pending" for pid in queue):
                raise RuntimeError("queue/location/status mismatch")
            # Equal-tick FIFO uses event phase/order: completion before injection;
            # IDs order events WITHIN each phase, not across both phases.
            order = [self.packets[pid].queued_tick for pid in queue]
            if order != sorted(order):
                raise RuntimeError("local receive FIFO order violated")
        pending = {pid for pid, p in self.packets.items() if p.status == "pending"}
        if len(stored) != len(set(stored)) or set(stored) != pending:
            raise RuntimeError("single sender-copy conservation violated")
        expected_reserved = [0] * self.cfg.orbit.n
        incident = []
        for pid, transfer in self.active.items():
            packet = self.packets[pid]
            if pid not in pending or transfer.sender != packet.location:
                raise RuntimeError("active transfer lacks sender copy")
            incident.extend((transfer.sender, transfer.receiver))
            expected_reserved[transfer.receiver] += packet.size_bytes
        if len(incident) != len(set(incident)) or set(incident) != self.busy:
            raise RuntimeError("single incident transfer invariant violated")
        if expected_reserved != self.reserved:
            raise RuntimeError("receiver reservation accounting mismatch")
        terminal = {pid for pid, p in self.packets.items() if p.status in ("delivered", "failed")}
        if terminal != self.terminal_ids:
            raise RuntimeError("terminal ledger/status mismatch")

    def run(self):
        if self._ran:
            raise RuntimeError("a Simulator instance is single-use")
        self._ran = True
        started = perf_counter()
        injection_index = 0
        # Result of the OPT-5 note below (T056, T048 and BASELINE are task labels of the project history, not
        # files of this export): a packet fails with reason 'ttl' only if it is 'pending' and expiry_tick <= tick,
        # in ascending packet id; the heap only avoids scanning every packet at every tick.
        # T056 OPT-5 (DESIGN T048 Q5 O-5a). The BASELINE scanned every packet in id order at every
        # tick and terminated those with status 'pending' and expiry_tick <= tick. A packet is
        # 'pending' only between admission and its terminal transition, so only packets whose
        # expiry_tick <= tick can matter: a min-heap of (expiry_tick, packet_id), built once, yields
        # exactly those ids; they are sorted (BASELINE order) and judged on their LIVE status with the
        # BASELINE predicate. Entries that are not yet actionable ('scheduled' or still 'pending' with
        # a later expiry) are put back after the scan; terminal ones never become pending again.
        expiry_heap = [(p.expiry_tick, pid) for pid, p in self.packets.items()]
        heapq.heapify(expiry_heap)
        # Result of the OPT-6 note below: the per-tick snapshot checks are skipped only for the GeometryNetwork
        # this Simulator built itself (type unchanged, no instance attribute 'snapshot'); any other network is
        # validated at every tick.
        # T056 OPT-6. For the GeometryNetwork built by this Simulator none of the five per-tick
        # snapshot checks can fail (graph_from_positions returns an (n, n) bool matrix made
        # symmetric by `adjacency &= adjacency.T` with a cleared diagonal, and (n, n) float64 ranges
        # that are square roots of sums of squares of finite positions; positions_km already
        # raised OverflowError if radius**3 overflows). A caller-supplied (or replaced, or patched)
        # network is always checked exactly as in the BASELINE.
        own = self._own_network
        trusted_snapshots = (own is not None and self.network is own
                             and type(own) is _SELF_BUILT_NETWORK_TYPE and "snapshot" not in vars(own))
        # Order of one tick (ticks 0 .. horizon_tick; _schedule is not called at horizon_tick):
        #  1. complete the active transfers with finish_tick <= tick (ascending packet id) that also finish at or
        #     before the packet's expiry_tick, using the previous tick's geometry: the link is not re-checked here;
        #  2. take this tick's topology snapshot (validated unless trusted_snapshots);
        #  3. TTL scan: a 'pending' packet with expiry_tick <= tick fails with reason 'ttl' and its active
        #     transfer, if any, is cancelled. Step 1 runs first, so a hop that finishes exactly at expiry_tick counts.
        #     By reading, the elif branch of the scan is not reached when ttl_ticks >= 1: it could only see a
        #     'scheduled' packet, and such a packet has created_tick >= tick, hence expiry_tick > tick;
        #  4. each remaining active transfer is aborted with 'link_loss' if its edge is absent in the new snapshot,
        #     else with 'edge_tick_failure' if start_tick < tick < finish_tick, failure_probability != 0 and the
        #     failure sampler fires;
        #  5. inject the packets with created_tick == tick (after the cancellations and aborts above);
        #  6. _schedule, only if tick < horizon_tick;
        #  7. audit(), if cfg.audit_each_tick.
        for tick in range(self.cfg.horizon_tick + 1):
            self.tick = tick
            # Complete using the previous cell's geometry before the new sample.
            for pid, transfer in sorted(list(self.active.items())):
                if transfer.finish_tick <= tick and transfer.finish_tick <= self.packets[pid].expiry_tick:
                    self._complete(self.packets[pid])
            topology_start = perf_counter()
            adjacency, ranges = self.network.snapshot(tick)
            self.topology_seconds += perf_counter() - topology_start
            n = self.cfg.orbit.n
            if not trusted_snapshots and (adjacency.shape != (n, n) or ranges.shape != (n, n)
                    or not np.isin(adjacency, [0, 1]).all() or np.diag(adjacency).any()
                    or not np.array_equal(adjacency, adjacency.T)
                    or not np.isfinite(ranges).all() or (ranges < 0).any()):
                raise ValueError("network must return symmetric binary graph and finite nonnegative km ranges")
            due = []
            while expiry_heap and expiry_heap[0][0] <= tick:
                due.append(heapq.heappop(expiry_heap)[1])
            not_actionable = []
            for pid in sorted(due):
                packet = self.packets[pid]
                if packet.status == "pending" and packet.expiry_tick <= tick:
                    self._terminal(packet, "failed", "ttl")
                elif packet.status in ("scheduled", "pending"):
                    not_actionable.append((packet.expiry_tick, pid))
            for entry in not_actionable:
                heapq.heappush(expiry_heap, entry)
            for pid, transfer in sorted(list(self.active.items())):
                packet = self.packets[pid]
                if not adjacency[transfer.sender, transfer.receiver]:
                    self._abort(packet, "link_loss")
                elif (transfer.start_tick < tick and transfer.finish_tick > tick
                      and self.cfg.failure_probability != 0
                      and self.failure_sampler(self.cfg.failure_seed, transfer.sender, transfer.receiver,
                                               tick, self.cfg.failure_probability)):
                    self._abort(packet, "edge_tick_failure")
            while injection_index < len(self.records) and self.records[injection_index].created_tick == tick:
                self._inject(self.packets[self.records[injection_index].packet_id])
                injection_index += 1
            if tick < self.cfg.horizon_tick:
                self._schedule(adjacency, ranges)
            if self.cfg.audit_each_tick:
                self.audit()
        self.audit()
        simulation_seconds = perf_counter() - started
        if injection_index != len(self.records) or any(p.status not in ("delivered", "failed", "pending") for p in self.packets.values()):
            raise RuntimeError("not every generated packet has a conserved outcome")
        terminal_events = [e["packet_id"] for e in self.events if e["kind"] == "terminal"]
        if len(terminal_events) != len(set(terminal_events)) or set(terminal_events) != self.terminal_ids:
            raise RuntimeError("terminal event/ledger mismatch")
        if self.counts["admitted"] + self.counts["injection_rejected"] != len(self.records):
            raise RuntimeError("injection conservation mismatch")
        return self.result(simulation_seconds)

    def result(self, simulation_seconds):
        # Fractions use all generated packets as denominator (rejected injections included). delay_s, mean and
        # median cover delivered packets only. goodput_bits_s = 8 * delivered_bytes / observation_end_s (whole
        # observation, not the traffic window). Packets still pending at the end are neither failed nor delivered.
        values = list(self.packets.values())
        delivered = [p for p in values if p.status == "delivered"]
        failed = [p for p in values if p.status == "failed"]
        pending = [p for p in values if p.status == "pending"]
        generated = len(values)
        if len(delivered) + len(failed) + len(pending) != generated:
            raise RuntimeError("final packet conservation mismatch")
        delays = [(p.terminal_tick - p.created_tick) * self.cfg.tick_s for p in delivered]
        delivered_bytes = sum(p.size_bytes for p in delivered)
        fraction = lambda count: count / generated if generated else None
        metrics = {"generated": generated, "admitted": self.counts["admitted"],
                   "injection_rejected": self.counts["injection_rejected"],
                   "delivered": len(delivered), "failed": len(failed), "pending": len(pending),
                   "delivered_delay_denominator": len(delivered),
                   "delivered_mean_delay_s": mean(delays) if delays else None,
                   "delivered_median_delay_s": median(delays) if delays else None,
                   "failure_fraction": fraction(len(failed)), "pending_fraction": fraction(len(pending)),
                   "nondelivery_fraction": fraction(len(failed) + len(pending)),
                   "delivered_fraction": fraction(len(delivered)), "delivered_bytes": delivered_bytes,
                   "observation_duration_s": self.cfg.observation_end_s,
                   "goodput_bits_s": 8 * delivered_bytes / self.cfg.observation_end_s,
                   "terminal_reason_counts": dict(sorted(Counter(p.terminal_reason for p in delivered + failed).items())),
                   "abort_reason_counts": dict(sorted(self.abort_reasons.items())),
                   "transfer_and_route_counts": dict(sorted(self.counts.items())),
                   "conservation_checked": True}
        route_calls = self.counts["route_calls"]
        summary = {"schema": "ssn-simulation-result-v1", "policy": self.policy.name,
                   "metrics": metrics, "policy_details": self.policy.stats(),
                   "timing": {"supported_device": "cpu", "simulation_seconds": simulation_seconds,
                              "topology_snapshot_seconds": self.topology_seconds,
                              "topology_snapshot_builds": getattr(self.network, "snapshot_builds", None),
                              "route_calls": route_calls, "route_seconds": self.route_seconds,
                              "route_seconds_per_call": self.route_seconds / route_calls if route_calls else None,
                              "route_scope": "entire choose call, including GLR inference on misses; excludes context/masks"}}
        rows = []
        for p in sorted(values, key=lambda p: p.packet_id):
            transfer = self.active.get(p.packet_id)
            rows.append({"packet_id": p.packet_id, "source": p.source, "destination": p.destination,
                         "size_bytes": p.size_bytes, "created_tick": p.created_tick,
                         "expiry_tick": p.expiry_tick, "admitted": p.admitted, "status": p.status,
                         "terminal_tick": p.terminal_tick, "terminal_reason": p.terminal_reason,
                         "delay_s": (p.terminal_tick - p.created_tick) * self.cfg.tick_s if p.status == "delivered" else None,
                         "location": p.location, "hops": p.hops, "total_aborts": p.total_aborts,
                         "hop_failed_attempts": p.hop_failures, "source_header": p.header,
                         "visited": sorted(p.visited), "last_wait": p.last_wait,
                         "active_receiver": transfer.receiver if transfer else None,
                         "active_finish_tick": transfer.finish_tick if transfer else None})
        return {"summary": summary, "packets": rows, "events": self.events}


def simulate(cfg, records, policy, network=None, failure_sampler=edge_tick_failure):
    return Simulator(cfg, records, policy, network, failure_sampler).run()
