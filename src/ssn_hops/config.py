"""Strict resolved configuration. Defaults are reconstruction assumptions.

Input-feature modes (T022-S01; paper arXiv 2108.08523v1 never feeds link delay
f(e) to the network, its inputs are the original input and the 1/0.5
two-hop-encoded preprocessed input):

* TOPOLOGY_FEATURES (DEFAULT): low=[A], high=[A|Q]. Paper input set; the H0 row
  layout is an independent reconstruction, NOT the recovered author H0.
* ABLATION_FEATURES: legacy literal "topology_only_ablation". Accepted ALIAS with
  identical behaviour and identical legacy persisted spec; configs/checkpoints
  are NOT silently re-labelled (ModelConfig equality compares the literal).
* DELAY_FEATURES: OPTIONAL EXTENSION, not in the paper: low=[A|D], high=[A|Q|D]
  with propagation-delay channel D.
"""
from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
import math
from pathlib import Path

TOPOLOGY_FEATURES = "adjacency_spliced_two_hop"
ABLATION_FEATURES = "topology_only_ablation"  # legacy alias of TOPOLOGY_FEATURES behaviour
DELAY_FEATURES = "adjacency_spliced_two_hop_propagation_delay"  # optional extension
TOPOLOGY_ONLY_MODES = (TOPOLOGY_FEATURES, ABLATION_FEATURES)
SUPPORTED_FEATURES = (TOPOLOGY_FEATURES, ABLATION_FEATURES, DELAY_FEATURES)
LIGHT_SPEED_KM_S = 299792.458
DELAY_SCALE_S = 0.01
# Persisted inside dataset manifests and checkpoints (strict equality checks).
# Keep byte-identical for the delay extension and the legacy alias so archived
# datasets/checkpoints stay readable; never edit these two strings casually.
LEGACY_SPEC_AUTHORITY = "independent reconstruction assumption, NOT recovered author H0"
TOPOLOGY_SPEC_AUTHORITY = ("paper input set (original input + 1/0.5 two-hop-encoded input); "
                           "H0 row layout [A] / [A|Q] is an independent reconstruction, NOT recovered author H0")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


def integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class OrbitConfig:
    n: int = 132
    planes: int = 12
    earth_radius_km: float = 6371.0
    altitude_km: float = 1050.0
    inclination_deg: float = 53.0
    eccentricity: float = 0.0
    mu_km3_s2: float = 398600.4418
    walker_f: int = 1
    phase_mode: str = "independent_plane_offsets"
    epoch_s: float = 0.0
    range_km: float = 3500.0
    earth_los: bool = True

    def validate(self):
        integer(self.n, "n", 2)
        integer(self.planes, "planes")
        if self.planes > self.n or self.n % self.planes:
            raise ValueError("n must be divisible by planes")
        for key in ("earth_radius_km", "altitude_km", "mu_km3_s2", "range_km"):
            positive(getattr(self, key), key)
        finite_number(self.inclination_deg, "inclination_deg")
        if not 0 <= self.inclination_deg <= 180:
            raise ValueError("inclination_deg must be in [0,180]")
        finite_number(self.eccentricity, "eccentricity")
        if self.eccentricity != 0:
            raise ValueError("only eccentricity=0 circular orbits are implemented")
        integer(self.walker_f, "walker_f", 0)
        if self.walker_f >= self.planes:
            raise ValueError("walker_f must be smaller than planes")
        if self.phase_mode not in ("walker", "independent_plane_offsets"):
            raise ValueError("unsupported phase_mode")
        finite_number(self.epoch_s, "epoch_s")
        if type(self.earth_los) is not bool:
            raise ValueError("earth_los must be boolean")


@dataclass(frozen=True)
class DataConfig:
    train_seeds: list[int] = field(default_factory=lambda: [101, 102, 103, 104, 105, 106, 107, 108])
    val_seeds: list[int] = field(default_factory=lambda: [201, 202])
    test_seeds: list[int] = field(default_factory=lambda: [301, 302])
    snapshots_per_trajectory: int = 24
    step_s: float = 120.0
    start_s: float = 0.0
    mask_diagonal: bool = True

    def validate(self):
        seeds = []
        for split in ("train", "val", "test"):
            values = getattr(self, f"{split}_seeds")
            if not isinstance(values, list) or not values:
                raise ValueError(f"{split}_seeds must be a nonempty list")
            for value in values:
                integer(value, f"{split} seed", 0)
                if value >= 2**32:
                    raise ValueError("phase seeds must be smaller than 2**32")
            seeds.extend(values)
        if len(set(seeds)) != len(seeds):
            raise ValueError("trajectory seeds must be globally unique across all splits")
        integer(self.snapshots_per_trajectory, "snapshots_per_trajectory")
        positive(self.step_s, "step_s")
        finite_number(self.start_s, "start_s")
        if type(self.mask_diagonal) is not bool:
            raise ValueError("mask_diagonal must be boolean")


@dataclass(frozen=True)
class ModelConfig:
    gcn_width: int = 32
    dense_width: int = 64
    gcn_bias: bool = False
    dense_bias: bool = True
    # DEFAULT = paper input set (topology only). Delay is an explicit opt-in extension.
    features: str = TOPOLOGY_FEATURES
    feature_version: int = 1
    # delay_* / light_speed_km_s are fixed constants of the OPTIONAL delay extension.
    # They are inert in topology-only modes (kept at their fixed values; validated as before).
    delay_kind: str = "propagation_only"
    delay_scale_s: float = DELAY_SCALE_S
    light_speed_km_s: float = LIGHT_SPEED_KM_S
    orientation: str = "destination_candidate"

    def validate(self):
        integer(self.gcn_width, "gcn_width")
        integer(self.dense_width, "dense_width")
        if type(self.gcn_bias) is not bool or type(self.dense_bias) is not bool:
            raise ValueError("bias switches must be boolean")
        if self.features not in SUPPORTED_FEATURES:
            raise ValueError("unsupported feature definition; supported: "
                             f"{', '.join(SUPPORTED_FEATURES)} (legacy v1 topology config requires explicit migration)")
        if type(self.feature_version) is not int or self.feature_version != 1:
            raise ValueError("unsupported feature_version")
        if self.delay_kind != "propagation_only":
            raise ValueError("unsupported delay_kind")
        positive(self.delay_scale_s, "delay_scale_s")
        positive(self.light_speed_km_s, "light_speed_km_s")
        if self.delay_scale_s != DELAY_SCALE_S or self.light_speed_km_s != LIGHT_SPEED_KM_S:
            raise ValueError("feature v1 fixes delay_scale_s=0.01 and light_speed_km_s=299792.458")
        if self.orientation != "destination_candidate":
            raise ValueError("unsupported output orientation")

    @property
    def uses_delay(self):
        """True ONLY for the optional propagation-delay extension (not in the paper)."""
        return self.features == DELAY_FEATURES

    @property
    def feature_role(self):
        """Human-readable status. NOT persisted and NOT part of feature_spec."""
        if self.features == DELAY_FEATURES:
            return "optional extension (propagation-delay channel D); NOT stated in the paper"
        if self.features == ABLATION_FEATURES:
            return "legacy alias of the paper-faithful topology-only input set; H0 layout is a reconstruction"
        return "paper-faithful default topology-only input set; H0 layout is a reconstruction"

    @property
    def feature_spec(self):
        # Persisted in dataset manifests, checkpoints and plans; compared strictly.
        # Delay and legacy-alias outputs are byte-identical to the pre-T022 values on purpose.
        self.validate()
        if self.uses_delay:
            delay_kind = self.delay_kind
        elif self.features == ABLATION_FEATURES:
            delay_kind = "none_ablation"
        else:
            delay_kind = "none"
        authority = TOPOLOGY_SPEC_AUTHORITY if self.features == TOPOLOGY_FEATURES else LEGACY_SPEC_AUTHORITY
        return {"schema": "ssn-input-features-v1", "mode": self.features,
                "version": self.feature_version,
                "delay_kind": delay_kind,
                "delay_scale_s": self.delay_scale_s if self.uses_delay else None,
                "light_speed_km_s": self.light_speed_km_s if self.uses_delay else None,
                "low": "[A|D]" if self.uses_delay else "[A]",
                "high": "[A|Q|D]" if self.uses_delay else "[A|Q]",
                "mask": "absent links and diagonal zero", "dtype": "float32",
                "propagation": "original binary A with GCN A+I normalization",
                "authority": authority}


def require_supported_model(model_config):
    """Mode-agnostic validity check: accepts every supported feature mode.

    Rejects only non-ModelConfig objects and unknown/inconsistent configurations
    (via ModelConfig.validate). It does NOT prefer or require delay mode. Strict
    mismatch protection between modes/checkpoints lives in ModelConfig equality and
    feature_spec comparisons at the load/preflight sites, not here.
    """
    if not isinstance(model_config, ModelConfig):
        raise ValueError("model configuration must be a ModelConfig")
    model_config.validate()
    return model_config


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 17
    epochs: int = 100
    batch_size: int = 4
    learning_rate: float = 0.001
    beta: float = 0.00001
    patience: int = 15
    device: str = "cpu"
    deterministic: bool = True
    threads: int = 1
    optimizer: str = "Adam"
    adam_betas: list[float] = field(default_factory=lambda: [0.9, 0.999])
    adam_eps: float = 1e-8

    def validate(self):
        integer(self.seed, "training seed", 0)
        if self.seed >= 2**32:
            raise ValueError("training seed must be smaller than 2**32")
        for key in ("epochs", "batch_size", "patience", "threads"):
            integer(getattr(self, key), key)
        positive(self.learning_rate, "learning_rate")
        positive(self.adam_eps, "adam_eps")
        finite_number(self.beta, "beta")
        if self.beta < 0:
            raise ValueError("beta must be finite and nonnegative")
        if self.optimizer != "Adam":
            raise ValueError("only Adam is implemented")
        if not isinstance(self.adam_betas, list) or len(self.adam_betas) != 2:
            raise ValueError("adam_betas must be a list of length two")
        for index, value in enumerate(self.adam_betas):
            finite_number(value, f"adam_betas[{index}]")
            if not 0 <= value < 1:
                raise ValueError("adam_betas must lie in [0,1)")
        if type(self.deterministic) is not bool:
            raise ValueError("deterministic must be boolean")
        if not isinstance(self.device, str):
            raise ValueError("device must be a string")


@dataclass(frozen=True)
class Config:
    schema_version: int = 2
    orbit: OrbitConfig = field(default_factory=OrbitConfig)
    data: DataConfig = field(default_factory=DataConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    train: TrainConfig = field(default_factory=TrainConfig)

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("unsupported configuration schema; migrate v1 configs explicitly and retrain")
        for section in (self.orbit, self.data, self.model, self.train):
            section.validate()
        return self

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return content_hash(self.to_dict())

    @property
    def data_key(self):
        # Dataset ARRAYS (positions, adjacency, labels, masks) depend only on orbit+data,
        # never on model.features (verified by reading data.py, T022-S01). The manifest
        # separately records feature_spec and re-checks it, so archived manifests stay
        # valid only while the persisted feature_spec bytes stay unchanged.
        return content_hash({"schema_version": 1, "orbit": asdict(self.orbit), "data": asdict(self.data)})


def _section(cls, value):
    if not isinstance(value, dict):
        raise ValueError(f"{cls.__name__} must be an object")
    unknown = set(value) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"unknown {cls.__name__} fields: {sorted(unknown)}")
    return cls(**value)


def from_dict(value):
    if not isinstance(value, dict):
        raise ValueError("configuration must be an object")
    unknown = set(value) - {"schema_version", "orbit", "data", "model", "train"}
    if unknown:
        raise ValueError(f"unknown configuration fields: {sorted(unknown)}")
    return Config(
        schema_version=value.get("schema_version", 2),
        orbit=_section(OrbitConfig, value.get("orbit", {})),
        data=_section(DataConfig, value.get("data", {})),
        model=_section(ModelConfig, value.get("model", {})),
        train=_section(TrainConfig, value.get("train", {})),
    ).validate()


def dataset_config(value):
    """Read-only migration of archived v1 metadata, NEVER weights/config CLI.

    Caller verifies the original raw config hash. Legacy arrays remain usable:
    positions, geometry and hop labels were already archived. This does not
    promote a legacy model to delay mode or rewrite its provenance. A v1 archive
    is a topology-only input set; it maps to the legacy alias literal (identical
    behaviour to TOPOLOGY_FEATURES, byte-stable persisted spec).
    """
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return from_dict(value)
    if type(value["schema_version"]) is not int:
        raise ValueError("invalid legacy dataset configuration schema")
    model = value.get("model", {})
    old_fields = {"gcn_width", "dense_width", "gcn_bias", "dense_bias", "features", "orientation"}
    if not isinstance(model, dict) or set(model) != old_fields:
        raise ValueError("legacy dataset requires a fully resolved v1 model config")
    if model["features"] != "adjacency_and_spliced_exclusive_two_hop":
        raise ValueError("unsupported legacy dataset features")
    updated = dict(value)
    updated["schema_version"] = 2
    updated["model"] = {**model, "features": ABLATION_FEATURES}
    return from_dict(updated)


def load_config(path):
    with Path(path).open(encoding="utf-8") as handle:
        return from_dict(json.load(handle))
