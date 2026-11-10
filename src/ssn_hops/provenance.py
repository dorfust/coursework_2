"""No shell calls, credentials, external datasets or fabricated result evidence."""
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import sys
import torch

SOURCES = {
    "contract": {"path": "Repo_Orchestrator_2/tasks/T002.md", "commit": "ac6378bddcf31873dbe0c4f5f891d86920826ee2"},
    "feature_contract": {"path": "Repo_Orchestrator_2/tasks/T011.md", "commit": "bc2e98e6a21c1662e9fb61b18998d12be8a3356e", "step": "R3/A01/S01"},
    "T001": {"path": "Repo_Research_2/artifacts/T001/", "commit": "378443719a6b4b48beeeba5d557b22f4093fc735"},
    "T007": {"path": "Repo_Research_2/artifacts/T007/", "commit": "759491fc63b55a951cdab8a985cb0310e0e69dad"},
    "paper": "arXiv:2108.08523v1 (2021-08-19)",
    "implementation": "independent reconstruction, not original code or published-performance equality",
}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes():
    root = Path(__file__).resolve().parent
    return {path.name: file_sha256(path) for path in sorted(root.glob("*.py"))}


def environment():
    versions = {}
    for name in ("numpy", "torch", "torch-geometric", "ssn-hop-reconstruction", "pytest"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return {"python": sys.version, "platform": platform.platform(), "packages": versions,
            "torch_cuda_build": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(), "torch_threads": torch.get_num_threads()}


def provenance(revision):
    return {"declared_checkout_revision": revision, "revision_is_user_supplied": True,
            "sources": SOURCES, "source_sha256": source_hashes(), "environment": environment()}


def write_json(path, value):
    # Exclusive creation guards evidence against accidental overwrite.
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)
