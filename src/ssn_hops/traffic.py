"""Predetermined traffic and stateless, edge/tick-keyed transfer-abort trials."""
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import random
from .config import content_hash, integer
from .sim_config import ticks


# created_tick counts ticks of cfg.tick_s seconds; size_bytes is in bytes. validate() requires
# non-negative integer ids and ticks, distinct endpoints below cfg.orbit.n, created_tick below
# ticks(cfg.traffic_end_s, cfg.tick_s) and size_bytes equal to cfg.packet_bytes.
@dataclass(frozen=True)
class TrafficRecord:
    packet_id: int
    created_tick: int
    source: int
    destination: int
    size_bytes: int

    def validate(self, cfg):
        for key in ("packet_id", "created_tick", "source", "destination"):
            integer(getattr(self, key), key, 0)
        integer(self.size_bytes, "size_bytes")
        if max(self.source, self.destination) >= cfg.orbit.n or self.source == self.destination:
            raise ValueError("traffic endpoints must be distinct node IDs in [0,N)")
        if self.created_tick >= ticks(cfg.traffic_end_s, cfg.tick_s):
            raise ValueError("traffic time must lie in [0, traffic_end_s)")
        if self.size_bytes != cfg.packet_bytes:
            raise ValueError("trace packet size differs from configured size")


def make_trace(cfg):
    """Build the packet list: one packet per arrival tick 0, step, 2*step, ... below stop.

    stop and step are the tick counts of traffic_end_s and arrival_interval_s (see ticks in
    sim_config). Randomness: random.Random(traffic_seed). For each packet the source is drawn
    first, then the destination from the other n-1 nodes (a draw in [0, n-1), raised by one when
    it is not below the source). The call order is part of what determines the trace.
    packet_id is the arrival index counted from 0 and every packet has size cfg.packet_bytes.
    """
    cfg.validate()
    rng = random.Random(cfg.traffic_seed)
    records = []
    stop = ticks(cfg.traffic_end_s, cfg.tick_s)
    step = ticks(cfg.arrival_interval_s, cfg.tick_s)
    for packet_id, tick in enumerate(range(0, stop, step)):
        source = rng.randrange(cfg.orbit.n)
        destination = rng.randrange(cfg.orbit.n - 1)
        if destination >= source:
            destination += 1
        records.append(TrafficRecord(packet_id, tick, source, destination, cfg.packet_bytes))
    return records


# Returns a NEW list sorted by (created_tick, packet_id); the input list is not sorted in place.
# Checks that every item is a TrafficRecord, validates it and rejects a repeated packet_id.
def validate_records(records, cfg):
    ids = set()
    for record in records:
        if not isinstance(record, TrafficRecord):
            raise ValueError("trace must contain TrafficRecord values")
        record.validate(cfg)
        if record.packet_id in ids:
            raise ValueError("duplicate traffic ID")
        ids.add(record.packet_id)
    return sorted(records, key=lambda r: (r.created_tick, r.packet_id))


# Returns a dict with the keys schema ("ssn-traffic-v1"), trace_key, records (dicts, in the
# order given by validate_records) and sha256, the content_hash of the first three keys.
def trace_document(records, cfg):
    rows = [asdict(r) for r in validate_records(records, cfg)]
    body = {"schema": "ssn-traffic-v1", "trace_key": cfg.trace_key, "records": rows}
    return {**body, "sha256": content_hash(body)}


# Checks a loaded trace document without any file access; every failure is reported as
# ValueError (the TypeError from TrafficRecord(**row) is converted). The last check compares
# trace_document(records, cfg) with the input, so the stored records must already be in
# canonical order and equal to their re-serialised form.
def read_trace(document, cfg):
    if not isinstance(document, dict) or set(document) != {"schema", "trace_key", "records", "sha256"}:
        raise ValueError("invalid traffic document fields")
    body = {key: document[key] for key in ("schema", "trace_key", "records")}
    if body["schema"] != "ssn-traffic-v1" or body["trace_key"] != cfg.trace_key:
        raise ValueError("traffic schema/config key mismatch")
    if content_hash(body) != document["sha256"]:
        raise ValueError("traffic hash mismatch")
    if not isinstance(body["records"], list):
        raise ValueError("records must be a list")
    try:
        records = [TrafficRecord(**row) for row in body["records"]]
    except TypeError as exc:
        raise ValueError("invalid traffic record fields") from exc
    records = validate_records(records, cfg)
    if trace_document(records, cfg) != document:
        raise ValueError("traffic records must have canonical time/ID order")
    return records


def edge_tick_failure(seed, u, v, tick, probability):
    """Exact-p Bernoulli construction using rejection, not reciprocal quantization.

    SHA256 domain-separated blocks provide deterministic pseudo-random bits. p is
    interpreted as the exact rational represented by the supplied Python number.
    There is no mutable RNG consumption and no persistent edge outage state.
    """
    integer(seed, "failure seed", 0)
    integer(u, "u", 0)
    integer(v, "v", 0)
    integer(tick, "tick", 0)
    if u == v:
        raise ValueError("self-edge failure key")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
        raise ValueError("probability must be in [0,1]")
    if probability == 0:
        return False
    if probability == 1:
        return True
    numerator, denominator = Fraction(probability).as_integer_ratio()
    width = (denominator - 1).bit_length()
    # The outcome depends only on seed, the unordered pair {u, v}, tick and probability. The
    # prefix text below is part of the key, so changing it changes every outcome. No state is
    # kept between calls.
    prefix = f"ssn-edge-tick-v1:{seed}:{min(u,v)}:{max(u,v)}:{tick}:".encode("ascii")
    # Wide denominators (e.g. subnormal floats) use more than one hash block.
    blocks = (width + 255) // 256
    # Rejection loop: a draw of width bits is accepted only if it is below denominator. When the
    # denominator is a power of two, width bits cover exactly denominator values, so every draw
    # is accepted.
    attempt = 0
    while True:
        raw = b"".join(hashlib.sha256(prefix + f"{attempt}:{block}".encode("ascii")).digest()
                       for block in range(blocks))
        value = int.from_bytes(raw, "big") & ((1 << width) - 1)
        if value < denominator:
            return value < numerator
        attempt += 1
