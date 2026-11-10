"""Dynamic reconstruction settings; no author experiment defaults are asserted."""
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from .config import OrbitConfig, _section, content_hash, integer, positive


def ticks(seconds, dt, name="time"):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    value = seconds / dt
    rounded = round(value)
    if not math.isclose(value, rounded, rel_tol=0, abs_tol=1e-7):
        raise ValueError(f"{name} must be a multiple of tick_s")
    return int(rounded)


def service_ticks(size_bytes, rate_bytes_s, distance_km, light_speed_km_s, dt):
    """Serialization + start-distance propagation; completion rounded UP to grid."""
    positive(size_bytes, "size_bytes")
    positive(rate_bytes_s, "rate_bytes_s")
    positive(light_speed_km_s, "light_speed_km_s")
    positive(dt, "dt")
    if not math.isfinite(distance_km) or distance_km < 0:
        raise ValueError("distance_km must be finite and nonnegative")
    raw = (size_bytes / rate_bytes_s + distance_km / light_speed_km_s) / dt
    # Remove only machine-level noise at an exact grid boundary, not a full tick.
    return max(1, math.ceil(raw - 1e-12))


@dataclass(frozen=True)
class SimulationConfig:
    schema: str = "ssn-simulation-config-v1"
    orbit: OrbitConfig = field(default_factory=OrbitConfig)
    phase_seed: int = 401
    traffic_seed: int = 501
    failure_seed: int = 601
    tick_s: float = 0.1
    traffic_end_s: float = 600.0
    observation_end_s: float = 900.0
    arrival_interval_s: float = 1.0
    packet_bytes: int = 18000
    ttl_s: float = 300.0
    buffer_bytes: int = 16000000
    rate_bytes_s: float = 12500.0
    light_speed_km_s: float = 299792.458
    failure_probability: float = 0.04
    additional_retries: int = 3
    torch_threads: int = 1
    audit_each_tick: bool = True

    def validate(self):
        if self.schema != "ssn-simulation-config-v1":
            raise ValueError("unsupported simulation schema")
        self.orbit.validate()
        for name in ("phase_seed", "traffic_seed", "failure_seed"):
            integer(getattr(self, name), name, 0)
            if getattr(self, name) >= 2**32:
                raise ValueError(f"{name} must be < 2**32")
        for name in ("tick_s", "traffic_end_s", "observation_end_s", "arrival_interval_s",
                     "ttl_s", "rate_bytes_s", "light_speed_km_s"):
            positive(getattr(self, name), name)
        for name in ("packet_bytes", "buffer_bytes", "torch_threads"):
            integer(getattr(self, name), name)
        integer(self.additional_retries, "additional_retries", 0)
        for name in ("traffic_end_s", "observation_end_s", "arrival_interval_s", "ttl_s"):
            if ticks(getattr(self, name), self.tick_s, name) < 1:
                raise ValueError(f"{name} must span at least one tick")
        if self.observation_end_s < self.traffic_end_s:
            raise ValueError("observation must cover the entire traffic horizon")
        p = self.failure_probability
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("failure_probability must be in [0,1]")
        if type(self.audit_each_tick) is not bool:
            raise ValueError("audit_each_tick must be boolean")
        return self

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return content_hash(self.to_dict())

    @property
    def trace_key(self):
        # Excludes policy, phase, failures and link rate for paired sensitivities.
        return content_hash({"n": self.orbit.n, "traffic_seed": self.traffic_seed,
                             "tick_s": self.tick_s, "traffic_end_s": self.traffic_end_s,
                             "arrival_interval_s": self.arrival_interval_s,
                             "packet_bytes": self.packet_bytes})

    @property
    def horizon_tick(self):
        return ticks(self.observation_end_s, self.tick_s)

    @property
    def ttl_ticks(self):
        return ticks(self.ttl_s, self.tick_s)


def from_sim_dict(value):
    if not isinstance(value, dict):
        raise ValueError("simulation config must be an object")
    data = dict(value)
    data["orbit"] = _section(OrbitConfig, data.get("orbit", {}))
    return _section(SimulationConfig, data).validate()


def load_sim_config(path):
    with Path(path).open(encoding="utf-8") as handle:
        return from_sim_dict(json.load(handle))
