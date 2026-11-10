"""Persist exact graph labels and whole-trajectory split manifests, no random split."""
from itertools import combinations
from pathlib import Path
import hashlib
import numpy as np
from .config import content_hash, dataset_config
from .geometry import make_trajectory, graph_from_positions
from .graph import shortest_hops, validate_adjacency
from .provenance import file_sha256, provenance, read_json, write_json

SPLITS = ("train", "val", "test")


def adjacency_hash(array):
    return hashlib.sha256(np.asarray(array, dtype=np.uint8).tobytes()).hexdigest()


def validate_manifest(manifest):
    version = manifest.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported dataset manifest schema")
    # Verify ORIGINAL archived metadata before read-only v1 migration.
    if manifest.get("config_sha256") != content_hash(manifest["config"]):
        raise ValueError("manifest configuration hash mismatch")
    if manifest["config"].get("schema_version") != version:
        raise ValueError("manifest/config schema mismatch")
    cfg = dataset_config(manifest["config"])
    if manifest.get("data_key") != cfg.data_key:
        raise ValueError("manifest configuration hash mismatch")
    if version == 2 and manifest.get("feature_provenance") != cfg.model.feature_spec:
        raise ValueError("manifest feature provenance mismatch")
    seeds, ids, phase_ids = set(), set(), set()
    for split in SPLITS:
        entry = manifest["splits"][split]
        if entry["file"] != f"{split}.npz":
            raise ValueError("unexpected split filename")
        expected_seeds = getattr(cfg.data, f"{split}_seeds")
        trajectories = entry["trajectories"]
        if [row["seed"] for row in trajectories] != expected_seeds:
            raise ValueError("manifest split seeds differ from resolved configuration")
        if entry["snapshot_count"] != len(trajectories) * cfg.data.snapshots_per_trajectory:
            raise ValueError("manifest snapshot count mismatch")
        for row in trajectories:
            trajectory = make_trajectory(cfg.orbit, row["seed"])
            if row["trajectory_id"] != trajectory.trajectory_id or row["parameters"] != trajectory.metadata():
                raise ValueError("realized phase provenance mismatch")
            expected_times = [cfg.data.start_s + i * cfg.data.step_s
                              for i in range(cfg.data.snapshots_per_trajectory)]
            if row["times_s"] != expected_times:
                raise ValueError("manifest time sequence mismatch")
            phase_id = (tuple(row["parameters"]["raan_rad"]), tuple(row["parameters"]["plane_phase_rad"]))
            if row["seed"] in seeds or row["trajectory_id"] in ids or phase_id in phase_ids:
                raise ValueError("duplicate trajectory/phase across split manifest")
            seeds.add(row["seed"])
            ids.add(row["trajectory_id"])
            phase_ids.add(phase_id)
    return cfg


def generate_dataset(cfg, output, revision):
    cfg.validate()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 2, "config": cfg.to_dict(), "config_sha256": cfg.sha256,
                "data_key": cfg.data_key, "feature_provenance": cfg.model.feature_spec,
                "provenance": provenance(revision), "splits": {}}
    unique_graphs = {}
    for split in SPLITS:
        positions, graphs, labels, masks, rows = [], [], [], [], []
        hashes = set()
        for seed in getattr(cfg.data, f"{split}_seeds"):
            trajectory = make_trajectory(cfg.orbit, seed)
            times = [cfg.data.start_s + i * cfg.data.step_s for i in range(cfg.data.snapshots_per_trajectory)]
            rows.append({"seed": seed, "trajectory_id": trajectory.trajectory_id,
                         "parameters": trajectory.metadata(), "times_s": times})
            for time_s in times:
                xyz = trajectory.positions_km(time_s)
                adjacency, _ = graph_from_positions(xyz, cfg.orbit)
                target, mask = shortest_hops(adjacency, cfg.data.mask_diagonal)
                positions.append(xyz)
                graphs.append(adjacency)
                labels.append(target)
                masks.append(mask)
                hashes.add(adjacency_hash(adjacency))
        filename = f"{split}.npz"
        np.savez_compressed(output / filename, positions_km=np.stack(positions),
                            adjacency=np.stack(graphs), target=np.stack(labels), mask=np.stack(masks))
        manifest["splits"][split] = {"file": filename, "sha256": file_sha256(output / filename),
                                     "snapshot_count": len(graphs), "trajectories": rows,
                                     "supervised_pairs": int(np.stack(masks).sum()),
                                     "unique_adjacencies": len(hashes)}
        unique_graphs[split] = hashes
    manifest["cross_split_exact_adjacency_overlap"] = {
        f"{a}:{b}": len(unique_graphs[a] & unique_graphs[b]) for a, b in combinations(SPLITS, 2)
    }
    manifest["split_protocol"] = "whole independent phase trajectories; adjacent times never split"
    validate_manifest(manifest)
    write_json(output / "manifest.json", manifest)
    return manifest


def load_dataset(directory, expected_config=None):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    cfg = validate_manifest(manifest)
    if expected_config is not None:
        expected_config.validate()
        if expected_config.data_key != cfg.data_key:
            raise ValueError("dataset geometry/split configuration differs from training configuration")
    data = {}
    n = cfg.orbit.n
    graph_sets = {}
    for split in SPLITS:
        entry = manifest["splits"][split]
        path = directory / entry["file"]
        if file_sha256(path) != entry["sha256"]:
            raise ValueError(f"{split} archive hash mismatch")
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {"positions_km", "adjacency", "target", "mask"}:
                raise ValueError("unexpected dataset array schema")
            arrays = {key: archive[key].copy() for key in archive.files}
        count = entry["snapshot_count"]
        for key in ("adjacency", "target", "mask"):
            if arrays[key].shape != (count, n, n):
                raise ValueError(f"invalid {split} {key} shape")
        if arrays["positions_km"].shape != (count, n, 3) or not np.isfinite(arrays["positions_km"]).all():
            raise ValueError("invalid saved coordinates")
        if arrays["mask"].dtype != np.bool_ or not np.issubdtype(arrays["target"].dtype, np.integer):
            raise ValueError("invalid mask/label dtype")
        index = 0
        hashes = set()
        for row in entry["trajectories"]:
            trajectory = make_trajectory(cfg.orbit, row["seed"])
            for time_s in row["times_s"]:
                xyz = trajectory.positions_km(time_s)
                if not np.allclose(arrays["positions_km"][index], xyz, rtol=1e-12, atol=1e-9):
                    raise ValueError("saved coordinates differ from phase/time manifest")
                expected_graph, _ = graph_from_positions(arrays["positions_km"][index], cfg.orbit)
                adjacency = validate_adjacency(arrays["adjacency"][index])
                if not np.array_equal(adjacency, expected_graph):
                    raise ValueError("saved adjacency differs from shared geometry")
                target, mask = shortest_hops(adjacency, cfg.data.mask_diagonal)
                if not np.array_equal(target, arrays["target"][index]) or not np.array_equal(mask, arrays["mask"][index]):
                    raise ValueError("saved labels/masks differ from exact BFS")
                hashes.add(adjacency_hash(adjacency))
                index += 1
        if int(arrays["mask"].sum()) != entry["supervised_pairs"] or len(hashes) != entry["unique_adjacencies"]:
            raise ValueError("manifest pair/graph counts differ from arrays")
        data[split] = arrays
        graph_sets[split] = hashes
    overlap = {f"{a}:{b}": len(graph_sets[a] & graph_sets[b]) for a, b in combinations(SPLITS, 2)}
    if manifest["cross_split_exact_adjacency_overlap"] != overlap:
        raise ValueError("manifest overlap counts differ from arrays")
    return data, manifest
