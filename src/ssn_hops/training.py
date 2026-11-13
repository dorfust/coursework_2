"""CPU-first training, restricted checkpoint loading and held-out static metrics."""
import math
from pathlib import Path
import random
import numpy as np
import torch
from .config import ABLATION_FEATURES, ModelConfig, from_dict
from .data import load_dataset
from .features import ranges_from_positions
from .graph import branch_inputs
from .loss import hop_loss, parameter_l2
from .model import HopRegressor
from .provenance import file_sha256, provenance, read_json, write_json

# Stored in every checkpoint payload and in best.json; compared against on load.
CHECKPOINT_FORMAT = "ssn-hops-fixed-n-v2"


def resolve_device(name):
    """Return a torch.device for name, or raise ValueError.

    Accepted: cpu without an index, and cuda (with or without an index) only if
    torch.cuda.is_available() is true and the index is below torch.cuda.device_count().
    Any other device type raises ValueError. A name that torch.device cannot parse is
    not handled in this function.
    """
    device = torch.device(name)
    if device.type == "cpu":
        if device.index is not None:
            raise ValueError("use cpu without an index")
    elif device.type == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA requested but not available; use cpu")
        if device.index is not None and device.index >= torch.cuda.device_count():
            raise ValueError("CUDA device index out of range")
    else:
        raise ValueError("only cpu and cuda[:index] are supported in this core")
    return device


def seed_training(config):
    """Set process-wide generator and library state from the training config.

    Seeds random, numpy.random and torch (and the CUDA generators if CUDA is available),
    sets the torch thread count to config.threads, calls
    torch.use_deterministic_algorithms(config.deterministic) and, if cudnn is available,
    sets cudnn benchmark to False and cudnn deterministic to config.deterministic. These
    calls change global state of the libraries; the function does not restore the previous
    values when it returns.
    """
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    torch.set_num_threads(config.threads)
    torch.use_deterministic_algorithms(config.deterministic)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = config.deterministic


def tensors_for_snapshot(arrays, index, device, model_config=None):
    """Build the model inputs and the label tensors of snapshot number index.

    model_config=None selects ModelConfig(), the default configuration (features is
    TOPOLOGY_FEATURES in config.py, so no delay inputs), not the config of any model:
    pass the model's own config when it may differ from the default. Ranges in km are
    computed from positions_km only if the config uses delay. Returns (inputs, target,
    mask): inputs is what branch_inputs returns, target is a float32 tensor and mask a
    bool tensor, all on device. Nothing is cached here: the inputs are rebuilt on every
    call.
    """
    config = model_config if model_config is not None else ModelConfig()
    config.validate()
    ranges = ranges_from_positions(arrays["positions_km"][index]) if config.uses_delay else None
    inputs = branch_inputs(arrays["adjacency"][index], device,
                           ranges_km=ranges, model_config=config)
    target = torch.tensor(arrays["target"][index], dtype=torch.float32, device=device)
    mask = torch.tensor(arrays["mask"][index], dtype=torch.bool, device=device)
    return inputs, target, mask


# Unit suffixes are part of the key names (mse_hops2, rmse_hops, ...). masked_pairs counts every
# False entry of arrays["mask"], whatever the reason. unreachable_offdiagonal_fraction divides by
# snapshots * n * (n - 1). The function calls model.eval() and does not switch back to train mode;
# train() calls model.train() at the start of every epoch.
@torch.no_grad()
def static_metrics(model, arrays, device):
    """Micro-average reachable supervised pairs, not per-snapshot averages.

    Evaluates RAW outputs, not inference diagonal overrides. Rounded accuracy uses
    torch.round (ties to even), no clipping. No packet latency or routing results.
    """
    model.eval()
    squared_sum = absolute_sum = signed_sum = max_abs = 0.0
    count = rounded_correct = 0
    snapshots_without_pairs = 0
    for index in range(len(arrays["adjacency"])):
        inputs, target, mask = tensors_for_snapshot(arrays, index, device, model.config)
        prediction = model(*inputs)
        if not bool(torch.isfinite(prediction).all()):
            raise ValueError("non-finite predictions during static evaluation")
        selected = int(mask.sum().item())
        if not selected:
            snapshots_without_pairs += 1
            continue
        errors = (prediction[mask] - target[mask]).double()
        squared_sum += errors.square().sum().item()
        absolute_sum += errors.abs().sum().item()
        signed_sum += errors.sum().item()
        max_abs = max(max_abs, errors.abs().max().item())
        rounded_correct += int((torch.round(prediction[mask]) == target[mask]).sum().item())
        count += selected
    if count == 0:
        raise ValueError("split has no reachable supervised pairs")
    target_array = arrays["target"]
    snapshots, n, _ = target_array.shape
    offdiag_total = snapshots * n * (n - 1)
    unreachable = int((target_array < 0).sum())
    return {"mse_hops2": squared_sum / count, "rmse_hops": math.sqrt(squared_sum / count),
            "mae_hops": absolute_sum / count, "signed_error_hops": signed_sum / count,
            "max_absolute_error_hops": max_abs, "rounded_exact_accuracy": rounded_correct / count,
            "supervised_pairs": count, "unreachable_offdiagonal_pairs": unreachable,
            "unreachable_offdiagonal_fraction": unreachable / offdiag_total,
            "masked_pairs": int(arrays["mask"].size - arrays["mask"].sum()),
            "snapshots": snapshots, "snapshots_without_supervised_pairs": snapshots_without_pairs,
            "metric_scope": "static raw all-pairs hop regression; no packet experiments"}


def _save_best(run, payload):
    # New run directory is mandatory. Atomic replacement is only inside that run.
    temporary = run / "best.pt.tmp"
    torch.save(payload, temporary)
    temporary.replace(run / "best.pt")


def feature_provenance(cfg, manifest):
    # Persisted in checkpoints and compared strictly on load. The delay-extension and
    # legacy-alias texts are byte-identical to pre-T022 values on purpose (archived
    # checkpoints stay loadable); only the new default literal gets new wording.
    # The returned dict is stored in the checkpoint and compared for equality in
    # load_trained_model (payload["feature_provenance"] != feature_provenance(cfg, manifest)).
    # A change to any text here, or a different manifest["schema_version"], gives a value that
    # differs from what an existing checkpoint stored.
    if cfg.model.uses_delay:
        scale_origin = "fixed physical 0.01 seconds; not fitted to any split"
    elif cfg.model.features == ABLATION_FEATURES:
        scale_origin = "not applicable; topology-only ablation has no delay input or delay scaling"
    else:
        scale_origin = "not applicable; paper-faithful topology-only input set has no delay input or delay scaling"
    return {"spec": cfg.model.feature_spec,
            "training_source": ("validated archived positions_km; Euclidean ranges in km"
                                if cfg.model.uses_delay else
                                "validated archived adjacency; topology-only inputs [A] and [A|Q], Q derived from A"),
            "dataset_manifest_schema": manifest["schema_version"],
            "dataset_array_schema": "positions_km,adjacency,target,mask unchanged v1",
            "scale_origin": scale_origin}


def train(cfg, dataset_dir, run_dir, revision):
    """Train one model, write a NEW run directory and return the best.json summary dict.

    Before anything is written: cfg is validated, the device is resolved, load_dataset
    must accept dataset_dir for cfg, and every split must contain supervised pairs
    (mask.any()). The run directory is then created with exist_ok=False and written in
    this order: config.json, dataset_manifest.json, provenance.json (with an
    input_features entry), then history.jsonl (opened with mode x; one canonical JSON
    line per epoch, flushed after each epoch) and best.pt (written through best.pt.tmp
    at every epoch that improves the validation MSE). After the epoch loop come
    best.json and, last, complete.json. There is no cleanup: if an exception ends the
    call, the files written so far stay. Such a directory has no complete.json, which
    load_trained_model requires, and a call with the same run_dir meets an existing
    directory while mkdir is called with exist_ok=False.
    """
    cfg.validate()
    device = resolve_device(cfg.train.device)
    data, manifest = load_dataset(dataset_dir, cfg)
    for split in ("train", "val", "test"):
        if not data[split]["mask"].any():
            raise ValueError(f"{split} split has no supervised pairs")
    seed_training(cfg.train)
    run = Path(run_dir)
    run.mkdir(parents=True, exist_ok=False)
    manifest_sha = file_sha256(Path(dataset_dir) / "manifest.json")
    feature_record = feature_provenance(cfg, manifest)
    write_json(run / "config.json", cfg.to_dict())
    write_json(run / "dataset_manifest.json", manifest)
    origin = provenance(revision)
    origin["input_features"] = feature_record
    write_json(run / "provenance.json", origin)
    model = HopRegressor(cfg.orbit.n, cfg.model).to(device)
    # weight_decay is 0.0 here; the parameter penalty is added through hop_loss
    # (beta * parameter_l2), not through the optimizer.
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.train.learning_rate,
                                 betas=tuple(cfg.train.adam_betas), eps=cfg.train.adam_eps,
                                 weight_decay=0.0)
    # Local shuffle stream independent of phase and model initialization streams.
    rng = np.random.default_rng(cfg.train.seed)
    best, best_epoch, stale = math.inf, 0, 0
    training_arrays = data["train"]
    history = []
    with (run / "history.jsonl").open("x", encoding="utf-8") as handle:
        from .config import canonical_json
        for epoch in range(1, cfg.train.epochs + 1):
            model.train()
            order = rng.permutation(len(training_arrays["adjacency"]))
            online_sse = 0.0
            online_pairs = optimizer_steps = skipped_batches = 0
            # A batch is up to cfg.train.batch_size snapshots of the shuffled order (a new
            # rng.permutation in every epoch). Each snapshot is passed through the model on its
            # own; the outputs are stacked and one pooled loss gives one optimizer step per
            # batch. The last batch may be smaller. A batch without any supervised pair is
            # skipped and counted in skipped_batches.
            for offset in range(0, len(order), cfg.train.batch_size):
                predictions, targets, masks = [], [], []
                for index in order[offset:offset + cfg.train.batch_size]:
                    inputs, target, mask = tensors_for_snapshot(training_arrays, int(index), device, cfg.model)
                    predictions.append(model(*inputs))
                    targets.append(target)
                    masks.append(mask)
                prediction, target, mask = torch.stack(predictions), torch.stack(targets), torch.stack(masks)
                if not bool(mask.any()):
                    skipped_batches += 1
                    continue
                optimizer.zero_grad(set_to_none=True)
                loss = hop_loss(prediction, target, mask, model, cfg.train.beta)
                if not bool(torch.isfinite(loss)):
                    raise ValueError("non-finite training loss")
                errors = (prediction[mask].detach() - target[mask]).double()
                online_sse += errors.square().sum().item()
                online_pairs += int(mask.sum().item())
                loss.backward()
                for parameter in model.parameters():
                    if parameter.grad is not None and not bool(torch.isfinite(parameter.grad).all()):
                        raise ValueError("non-finite gradient")
                optimizer.step()
                optimizer_steps += 1
            if online_pairs == 0:
                raise ValueError("training epoch has no supervised pairs")
            validation = static_metrics(model, data["val"], device)
            norm = float(parameter_l2(model).detach().cpu())
            # online_train_mse_hops2 is accumulated from the predictions made in train mode before
            # each optimizer step of this epoch (hops^2), not from a separate pass after the epoch.
            # validation is static_metrics on the validation split after the epoch; parameter_l2 is
            # the unsquared norm; validation_regularized_objective is validation MSE + beta * norm.
            record = {"epoch": epoch, "online_train_mse_hops2": online_sse / online_pairs,
                      "train_pairs": online_pairs, "optimizer_steps": optimizer_steps,
                      "skipped_empty_batches": skipped_batches, "parameter_l2": norm,
                      "validation": validation,
                      "validation_regularized_objective": validation["mse_hops2"] + cfg.train.beta * norm}
            history.append(record)
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            # Model selection: the checkpoint with the smallest validation MSE is kept. That is
            # validation["mse_hops2"] (micro-average over the supervised pairs of the validation
            # split, raw outputs), without the beta term; the regularized objective is only logged
            # in the record. The comparison is a strict "<", so on equal values the earlier epoch
            # stays. best starts at math.inf, so any finite first value counts as an improvement.
            # stale counts the epochs since the last strict improvement and is reset to 0 by one;
            # the loop ends when stale >= cfg.train.patience or after cfg.train.epochs epochs.
            if validation["mse_hops2"] < best:
                best, best_epoch, stale = validation["mse_hops2"], epoch, 0
                payload = {"format": CHECKPOINT_FORMAT, "config": cfg.to_dict(),
                           "config_sha256": cfg.sha256, "data_key": cfg.data_key,
                           "feature_provenance": feature_record,
                           "dataset_manifest_sha256": manifest_sha, "epoch": epoch,
                           "validation_mse_hops2": best, "revision": revision,
                           "model_state": {key: value.detach().cpu().clone() for key, value in model.state_dict().items()},
                           "optimizer_state": optimizer.state_dict(),
                           "selection": "minimum reachable-pair validation MSE; earliest epoch wins exact ties"}
                _save_best(run, payload)
            else:
                stale += 1
            if stale >= cfg.train.patience:
                break
    summary = {"format": CHECKPOINT_FORMAT, "best_epoch": best_epoch,
               "best_validation_mse_hops2": best, "epochs_run": len(history),
               "best_checkpoint_sha256": file_sha256(run / "best.pt"),
               "config_sha256": cfg.sha256, "dataset_manifest_sha256": manifest_sha,
               "feature_provenance": feature_record,
               "selection": "validation MSE only; test labels not used for tuning",
               "runtime_result_origin": "created by the executing user, not supplied precomputed"}
    write_json(run / "best.json", summary)
    write_json(run / "complete.json", {"training_finished": True, "epochs_run": len(history)})
    return summary


def validate_checkpoint_metadata(payload, expected_model_config=None):
    """Pure metadata guard, before state-dict loading. No legacy weight migration.

    Mode mismatch protection: expected_model_config is compared by full dataclass
    equality (incl. the features literal), so a checkpoint trained under one feature
    mode (or alias literal) is never silently loaded as another.
    """
    if payload.get("format") != CHECKPOINT_FORMAT:
        raise ValueError("incompatible checkpoint format; v1 topology weights require retraining")
    cfg = from_dict(payload["config"])
    if cfg.sha256 != payload["config_sha256"] or cfg.data_key != payload["data_key"]:
        raise ValueError("checkpoint configuration hash mismatch")
    record = payload.get("feature_provenance")
    if not isinstance(record, dict) or record.get("spec") != cfg.model.feature_spec:
        raise ValueError("checkpoint feature provenance mismatch")
    if expected_model_config is not None:
        expected_model_config.validate()
        if cfg.model != expected_model_config:
            raise ValueError("checkpoint model/input configuration differs from expected model")
    return cfg


def load_trained_model(run_dir, device_name="cpu", expected_model_config=None):
    """Load the best checkpoint of a finished run and return (model, metadata).

    Reads complete.json, best.json, best.pt, config.json, dataset_manifest.json and
    provenance.json from run_dir. The checks run in this order: training_finished is
    true in complete.json; the format in best.json; the SHA-256 of best.pt against
    best.json; best.pt is then loaded with weights_only=True and passed to
    validate_checkpoint_metadata (config hash, data_key, feature provenance, and equality
    with expected_model_config if one is given); config.json against the checkpoint
    config; best.json against the payload; the SHA-256 of dataset_manifest.json; the
    archived manifest through validate_manifest; the feature provenance recomputed by
    feature_provenance; the input_features entry of provenance.json; and finally
    load_state_dict with strict=True. The model is returned in eval mode on device_name;
    metadata is the payload without model_state and optimizer_state.
    """
    run = Path(run_dir)
    device = resolve_device(device_name)
    if read_json(run / "complete.json").get("training_finished") is not True:
        raise ValueError("run is not marked complete")
    summary = read_json(run / "best.json")
    if summary.get("format") != CHECKPOINT_FORMAT:
        raise ValueError("incompatible checkpoint format; retrain for v2 inputs")
    if file_sha256(run / "best.pt") != summary["best_checkpoint_sha256"]:
        raise ValueError("checkpoint file hash mismatch")
    # Tensors/primitives only. Never disable weights_only for an untrusted file.
    payload = torch.load(run / "best.pt", map_location="cpu", weights_only=True)
    cfg = validate_checkpoint_metadata(payload, expected_model_config)
    if read_json(run / "config.json") != cfg.to_dict():
        raise ValueError("run config and checkpoint config differ")
    for key in ("config_sha256", "dataset_manifest_sha256", "feature_provenance"):
        if summary[key] != payload[key]:
            raise ValueError(f"checkpoint summary {key} mismatch")
    if summary["best_epoch"] != payload["epoch"] or summary["best_validation_mse_hops2"] != payload["validation_mse_hops2"]:
        raise ValueError("checkpoint selection metadata mismatch")
    if file_sha256(run / "dataset_manifest.json") != payload["dataset_manifest_sha256"]:
        raise ValueError("saved input manifest hash mismatch")
    manifest = read_json(run / "dataset_manifest.json")
    from .data import validate_manifest
    archived_cfg = validate_manifest(manifest)
    if archived_cfg.data_key != cfg.data_key or payload["feature_provenance"] != feature_provenance(cfg, manifest):
        raise ValueError("checkpoint feature/data provenance mismatch")
    if read_json(run / "provenance.json").get("input_features") != payload["feature_provenance"]:
        raise ValueError("run feature provenance differs from checkpoint")
    model = HopRegressor(cfg.orbit.n, cfg.model)
    model.load_state_dict(payload["model_state"], strict=True)
    model.to(device).eval()
    # No resume claim: RNG/history/early-stop state aren't restored here.
    metadata = {key: value for key, value in payload.items() if key not in ("model_state", "optimizer_state")}
    return model, metadata


def evaluate(run_dir, dataset_dir, split, output, revision, device_name="cpu"):
    """Evaluate the checkpoint of run_dir on one split of the dataset it was trained on.

    The config is taken from the checkpoint and load_dataset checks the dataset against
    it. The SHA-256 of manifest.json in dataset_dir must equal the
    dataset_manifest_sha256 stored in the checkpoint, otherwise ValueError is raised.
    The result dict (metrics, checkpoint and config hashes, and provenance(revision) of
    the evaluating run) is written with write_json to output, after the parent folders
    of output have been created, and is also returned. split must be train, val or test;
    device_name defaults to cpu.
    """
    if split not in ("train", "val", "test"):
        raise ValueError("split must be train, val or test")
    model, metadata = load_trained_model(run_dir, device_name)
    cfg = from_dict(metadata["config"])
    data, manifest = load_dataset(dataset_dir, cfg)
    manifest_sha = file_sha256(Path(dataset_dir) / "manifest.json")
    if manifest_sha != metadata["dataset_manifest_sha256"]:
        raise ValueError("evaluation dataset differs from the training input manifest")
    metrics = static_metrics(model, data[split], next(model.parameters()).device)
    result = {"split": split, "checkpoint_epoch": metadata["epoch"],
              "checkpoint_sha256": file_sha256(Path(run_dir) / "best.pt"),
              "config_sha256": cfg.sha256, "dataset_manifest_sha256": manifest_sha,
              "feature_provenance": metadata["feature_provenance"],
              "cross_split_exact_adjacency_overlap": manifest["cross_split_exact_adjacency_overlap"],
              "metrics": metrics, "provenance": provenance(revision)}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)
    return result
