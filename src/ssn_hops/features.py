"""Pure NumPy physical inputs shared by archived training and packet inference.

Propagation-only D belongs to the OPTIONAL delay-extension mode, which is NOT
stated in the paper (T020 C002): the paper's inputs are the original input and
the 1/0.5 two-hop-encoded input only. D is a reconstruction assumption, not
recovered author H0. All physical values must be real, finite and nonnegative,
even when masked out.
"""
# Functions: validate_adjacency, real_array, validate_ranges, ranges_from_positions and
# delay_features. graph.py imports validate_adjacency from this module.
import numpy as np
from .config import ModelConfig


def validate_adjacency(adjacency):
    """Return the adjacency as a bool array of shape [N, N].

    Accepts bool, integer, unsigned or float arrays that hold only the values 0 and 1 and are
    square with N >= 2, symmetric and with a zero diagonal; otherwise ValueError is raised.
    The conversion uses astype(bool, copy=False), so for an input that is already bool the
    result may share memory with the caller's array: do not modify the result in place.
    """
    array = np.asarray(adjacency)
    if array.ndim != 2 or array.shape[0] != array.shape[1] or array.shape[0] < 2:
        raise ValueError("adjacency must be square [N,N], N>=2")
    if array.dtype.kind not in "buif" or not np.isfinite(array).all() or not np.isin(array, [0, 1]).all():
        raise ValueError("adjacency must be finite binary values")
    array = array.astype(bool, copy=False)
    if np.diag(array).any() or not np.array_equal(array, array.T):
        raise ValueError("adjacency must be undirected with zero diagonal")
    return array


# Accepts integer, unsigned or float arrays (not bool) of exactly the given shape and returns
# them as float64 (astype with copy=False, so an array that is already float64 may be returned
# without a copy). Non-finite values raise ValueError.
def real_array(value, shape, name):
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in "uif":
        raise ValueError(f"{name} must be a real finite array of shape {shape}")
    array = array.astype(np.float64, copy=False)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array


# ranges_km is [n, n] in km: finite, >= 0 and exactly symmetric (np.array_equal, no tolerance).
# The diagonal is not required to be zero.
def validate_ranges(ranges_km, n):
    ranges = real_array(ranges_km, (n, n), "ranges_km")
    if (ranges < 0).any() or not np.array_equal(ranges, ranges.T):
        raise ValueError("ranges_km must be nonnegative and symmetric")
    return ranges


# positions_km [N, 3] in km -> pairwise Euclidean distances [N, N] in km. The np.errstate block
# sets over and invalid handling to "ignore"; a non-finite result is then rejected by
# validate_ranges (ValueError).
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
    """Return the delay channel D as a float32 array of shape [N, N].

    Value for a linked pair: (range_km / light_speed_km_s) / delay_scale_s, with both constants
    taken from the model config; exactly 0 for the diagonal and for absent links.
    model_config must be a delay-mode config. With None the default ModelConfig() is used; if
    that default is a topology-only mode (graph.branch_inputs describes its default that way),
    the call raises ValueError.
    """
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
