"""Predetermined traffic and stateless, edge/tick-keyed transfer-abort trials."""
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import random
from .config import content_hash, integer
from .sim_config import ticks


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


def trace_document(records, cfg):
    rows = [asdict(r) for r in validate_records(records, cfg)]
    body = {"schema": "ssn-traffic-v1", "trace_key": cfg.trace_key, "records": rows}
    return {**body, "sha256": content_hash(body)}


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
    prefix = f"ssn-edge-tick-v1:{seed}:{min(u,v)}:{max(u,v)}:{tick}:".encode("ascii")
    # Wide denominators (e.g. subnormal floats) use more than one hash block.
    blocks = (width + 255) // 256
    attempt = 0
    while True:
        raw = b"".join(hashlib.sha256(prefix + f"{attempt}:{block}".encode("ascii")).digest()
                       for block in range(blocks))
        value = int.from_bytes(raw, "big") & ((1 << width) - 1)
        if value < denominator:
            return value < numerator
        attempt += 1
