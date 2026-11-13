"""Circular ECI geometry in km/seconds, independently written from analytic formulas."""
from dataclasses import dataclass
import math
import numpy as np
from .config import OrbitConfig, content_hash, integer


@dataclass(frozen=True)
class Trajectory:
    """One realised random phase configuration (see make_trajectory).

    raan_rad and plane_phase_rad hold NumPy arrays of angles in radians, one entry per plane.
    Because the fields hold arrays, compare trajectories by trajectory_id instead of comparing
    the objects.
    """
    config: OrbitConfig
    seed: int
    raan_rad: np.ndarray
    plane_phase_rad: np.ndarray

    # metadata() is what dataset manifests store and what trajectory_id hashes.
    # data.validate_manifest recomputes both from the seed and compares them with the stored
    # values, so a change to this dictionary makes manifests written earlier fail that comparison.
    def metadata(self):
        from dataclasses import asdict
        return {"orbit": asdict(self.config), "seed": self.seed,
                "raan_rad": self.raan_rad.tolist(), "plane_phase_rad": self.plane_phase_rad.tolist()}

    @property
    def trajectory_id(self):
        return content_hash(self.metadata())

    # Orbital period in seconds of the circular orbit (radius in km, mu in km^3/s^2).
    @property
    def period_s(self):
        radius = self.config.earth_radius_km + self.config.altitude_km
        return 2 * math.pi * math.sqrt(radius**3 / self.config.mu_km3_s2)

    def positions_km(self, time_s):
        """Node positions at time_s as an array of shape [N, 3] in km.

        time_s is in seconds; any finite value is accepted, also a negative one. The frame is the
        one named in the module docstring (ECI); no Earth rotation appears in this function.
        Node i lies in plane i // (n // planes) at slot i % (n // planes). The phase of a node is
        2*pi*slot/per_plane + plane_phase_rad[plane] + omega*(time_s - epoch_s), taken modulo 2*pi.
        """
        if not math.isfinite(time_s):
            raise ValueError("time_s must be finite")
        cfg = self.config
        per_plane = cfg.n // cfg.planes
        plane = np.repeat(np.arange(cfg.planes), per_plane)
        slot = np.tile(np.arange(per_plane), cfg.planes)
        radius = cfg.earth_radius_km + cfg.altitude_km
        omega = math.sqrt(cfg.mu_km3_s2 / radius**3)
        phase = (2 * np.pi * slot / per_plane + self.plane_phase_rad[plane]
                 + omega * (time_s - cfg.epoch_s)) % (2 * np.pi)
        raan = self.raan_rad[plane]
        ci = math.cos(math.radians(cfg.inclination_deg))
        si = math.sin(math.radians(cfg.inclination_deg))
        cu, su = np.cos(phase), np.sin(phase)
        co, so = np.cos(raan), np.sin(raan)
        return radius * np.column_stack((co * cu - so * su * ci,
                                        so * cu + co * su * ci, su * si))


def make_trajectory(config, seed):
    """Build the Trajectory for one phase seed (an int in [0, 2**32)); angles are in radians.

    All randomness comes from one np.random.default_rng(seed), drawn in this order:
    (1) a global RAAN rotation, (2) a common phase offset, (3) only if phase_mode is
    independent_plane_offsets, one more offset per plane. The draw order therefore determines
    the values. RAAN of plane p is 2*pi*p/planes plus the global rotation; the base phase of
    plane p is 2*pi*walker_f*p/n plus the common offset (plus the per-plane offset in the
    independent mode).
    """
    config.validate()
    integer(seed, "phase seed", 0)
    if seed >= 2**32:
        raise ValueError("phase seed must be smaller than 2**32")
    rng = np.random.default_rng(seed)
    plane = np.arange(config.planes)
    # Uniform RAAN spacing, one global random rotation, explicit floating-point F.
    raan = (2 * np.pi * plane / config.planes + rng.uniform(0, 2 * np.pi)) % (2 * np.pi)
    phase = 2 * np.pi * config.walker_f * plane / config.n + rng.uniform(0, 2 * np.pi)
    if config.phase_mode == "independent_plane_offsets":
        phase = phase + rng.uniform(0, 2 * np.pi, size=config.planes)
    return Trajectory(config, seed, raan, phase % (2 * np.pi))


# Returns (adjacency, ranges): adjacency is a bool [N, N] array, symmetric with a False diagonal
# (the last lines apply adjacency &= adjacency.T and clear the diagonal). ranges is the full
# [N, N] distance matrix in km, not limited to linked pairs. Positions with a norm below
# earth_radius_km raise ValueError. This file does not define the 50.4 deg mentioned in the
# docstring.
def graph_from_positions(positions_km, config):
    """One shared physical/advertised graph. Returns (binary adjacency, ranges_km).

    Range comparison is inclusive; a tangent to the spherical Earth is visible.
    No atmosphere, antenna constraints or interpretation of the unresolved 50.4 deg.
    """
    config.validate()
    xyz = np.asarray(positions_km, dtype=np.float64)
    if xyz.shape != (config.n, 3) or not np.isfinite(xyz).all():
        raise ValueError("positions must be a finite [N,3] array in km")
    if np.any(np.linalg.norm(xyz, axis=1) < config.earth_radius_km):
        raise ValueError("positions inside Earth are invalid")
    delta = xyz[None, :, :] - xyz[:, None, :]
    squared = np.sum(delta * delta, axis=-1)
    ranges = np.sqrt(squared)
    adjacency = ranges <= config.range_km
    if config.earth_los and xyz.flags.c_contiguous:
        # T056 OPT-7. The BASELINE b6f5f516 evaluates the line-of-sight expression for all N*N
        # pairs and then ANDs it into `adjacency`, so every entry whose range test failed is
        # False in the result whatever the expression gives there. Here the SAME expression is
        # evaluated only for the pairs that passed the range test (the diagonal included, as in
        # the BASELINE; ranges[i, i] == 0). `delta`, `squared` and `ranges` stay the full
        # BASELINE arrays. Every step below is the BASELINE step on gathered, C-contiguous
        # (m, 3) arrays: element-wise float64 operations plus np.sum over the last (contiguous)
        # axis of length 3, exactly the reduction the BASELINE applies to its (N, N, 3) arrays.
        # Bitwise-equality argument: Repo_Code_2/artifacts/T056/S02_CHANGED_PATHS.md section 3.
        # The baseline and the argument file cited above are not part of this source folder.
        rows, cols = np.nonzero(adjacency)
        if rows.size:
            origin = np.ascontiguousarray(xyz[rows])
            step = np.ascontiguousarray(delta[rows, cols])
            length2 = squared[rows, cols]
            # Closest point on the closed segment p_i -> p_j; safe for zero length.
            dot = np.sum(origin * step, axis=-1)
            t = np.zeros_like(length2)
            np.divide(-dot, length2, out=t, where=length2 > 0)
            t = np.clip(t, 0.0, 1.0)
            closest = origin + t[:, None] * step
            adjacency[rows, cols] = np.sum(closest * closest, axis=-1) >= config.earth_radius_km**2
    elif config.earth_los:
        # BASELINE code, verbatim, for position arrays that are not C-contiguous (the memory
        # layout of such inputs could change the layout of the temporaries below, which the
        # equality argument does not cover); the project itself always passes C-contiguous arrays.
        # Closest point on the closed segment p_i -> p_j; safe for zero length.
        dot = np.sum(xyz[:, None, :] * delta, axis=-1)
        t = np.zeros_like(squared)
        np.divide(-dot, squared, out=t, where=squared > 0)
        t = np.clip(t, 0.0, 1.0)
        closest = xyz[:, None, :] + t[..., None] * delta
        visible = np.sum(closest * closest, axis=-1) >= config.earth_radius_km**2
        adjacency &= visible
    adjacency &= adjacency.T  # Conservative treatment of a floating-point tangent.
    np.fill_diagonal(adjacency, False)
    return adjacency, ranges
