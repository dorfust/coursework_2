"""Pure NumPy physical inputs shared by archived training and packet inference.

Propagation-only D belongs to the OPTIONAL delay-extension mode, which is NOT
stated in the paper (T020 C002): the paper's inputs are the original input and
the 1/0.5 two-hop-encoded input only. D is a reconstruction assumption, not
recovered author H0. All physical values must be real, finite and nonnegative,
even when masked out.
"""
import numpy as np
from .config import ModelConfig


def validate_adjacency(adjacency):
    array = np.asarray(adjacency)
    if array.ndim != 2 or array.shape[0] != array.shape[1] or array.shape[0] < 2:
        raise ValueError("adjacency must be square [N,N], N>=2")
    if array.dtype.kind not in "buif" or not np.isfinite(array).all() or not np.isin(array, [0, 1]).all():
        raise ValueError("adjacency must be finite binary values")
    array = array.astype(bool, copy=False)
    if np.diag(array).any() or not np.array_equal(array, array.T):
        raise ValueError("adjacency must be undirected with zero diagonal")
    return array


def real_array(value, shape, name):
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in "uif":
        raise ValueError(f"{name} must be a real finite array of shape {shape}")
    array = array.astype(np.float64, copy=False)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array


def validate_ranges(ranges_km, n):
    ranges = real_array(ranges_km, (n, n), "ranges_km")
    if (ranges < 0).any() or not np.array_equal(ranges, ranges.T):
        raise ValueError("ranges_km must be nonnegative and symmetric")
    return ranges


def ranges_from_positions(positions_km):
    raw = np.asarray(positions_km)
    if raw.ndim != 2 or raw.shape[0] < 2 or raw.shape[1] != 3:
        raise ValueError("positions_km must be real finite [N,3], N>=2")
    xyz = real_array(raw, raw.shape, "positions_km")
    # Same Euclidean arithmetic/units as geometry.graph_from_positions.
    with np.errstate(over="ignore", invalid="ignore"):
        delta = xyz[None, :, :] - xyz[:, None, :]
        ranges = np.sqrt(np.sum(delta * delta, axis=-1))
    return validate_ranges(ranges, len(xyz))


def delay_features(adjacency, ranges_km, model_config=None):
    config = model_config if model_config is not None else ModelConfig()
    config.validate()
    if not config.uses_delay:
        raise ValueError("delay_features requires delay mode (the optional propagation-delay "
                         "extension), not a topology-only mode")
    array = validate_adjacency(adjacency)
    ranges = validate_ranges(ranges_km, len(array))
    # Mask BEFORE conversion; diagonal and absent links stay exactly zero.
    scaled = np.zeros_like(ranges)
    scaled[array] = (ranges[array] / config.light_speed_km_s) / config.delay_scale_s
    with np.errstate(over="ignore", invalid="ignore"):
        result = scaled.astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("delay feature is not finite float32")
    return result
