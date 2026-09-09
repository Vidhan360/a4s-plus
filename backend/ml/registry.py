"""Versioned model registry.

Artifacts live under ``ml/artifacts/<model_name>/<version>/`` and contain:

* ``model.pt``        — PyTorch ``state_dict`` (LSTM only)
* ``model.joblib``    — serialised estimator (scikit-learn models only)
* ``metadata.json``   — architecture, scaler, feature order, hyperparameters,
                        dataset provenance and the *measured* evaluation
                        metrics from the run that produced the artifact
* ``training_history.json`` — per-epoch loss/accuracy curves

``latest.json`` in each model directory records the current version, so the
backend loads a specific, reproducible artifact rather than whatever file
happens to be newest on disk.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ARTIFACT_ROOT = Path(__file__).resolve().parent / "artifacts"


def artifact_root() -> Path:
    """Resolve the artifact root, honouring ``A4S_ML_ARTIFACT_DIR``."""
    configured = os.getenv("A4S_ML_ARTIFACT_DIR")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    return DEFAULT_ARTIFACT_ROOT


@dataclass
class ModelArtifact:
    model_name: str
    version: str
    directory: Path
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def weights_path(self) -> Path:
        return self.directory / "model.pt"

    @property
    def estimator_path(self) -> Path:
        return self.directory / "model.joblib"

    @property
    def metadata_path(self) -> Path:
        return self.directory / "metadata.json"

    @property
    def history_path(self) -> Path:
        return self.directory / "training_history.json"

    def exists(self) -> bool:
        return self.metadata_path.exists()


def new_version(prefix: str = "v") -> str:
    """Timestamp-based, sortable, collision-free version identifier."""
    return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def model_dir(model_name: str) -> Path:
    return artifact_root() / model_name


def save_artifact(
    model_name: str,
    version: str,
    metadata: dict[str, Any],
    *,
    state_dict: Any | None = None,
    estimator: Any | None = None,
    history: dict[str, Any] | None = None,
    mark_latest: bool = True,
) -> ModelArtifact:
    directory = model_dir(model_name) / version
    directory.mkdir(parents=True, exist_ok=True)
    artifact = ModelArtifact(model_name, version, directory, metadata)

    if state_dict is not None:
        import torch

        torch.save(state_dict, artifact.weights_path)
    if estimator is not None:
        import joblib

        joblib.dump(estimator, artifact.estimator_path)

    payload = {
        "model_name": model_name,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    artifact.metadata_path.write_text(json.dumps(payload, indent=2, default=str))
    artifact.metadata = payload

    if history is not None:
        artifact.history_path.write_text(json.dumps(history, indent=2, default=str))

    if mark_latest:
        (model_dir(model_name) / "latest.json").write_text(
            json.dumps({"version": version, "updated_at": payload["created_at"]}, indent=2)
        )
    return artifact


def list_versions(model_name: str) -> list[str]:
    directory = model_dir(model_name)
    if not directory.exists():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_dir() and (p / "metadata.json").exists()
    )


def latest_version(model_name: str) -> str | None:
    pointer = model_dir(model_name) / "latest.json"
    if pointer.exists():
        try:
            version = json.loads(pointer.read_text()).get("version")
            if version and (model_dir(model_name) / version / "metadata.json").exists():
                return str(version)
        except (ValueError, OSError):
            pass
    versions = list_versions(model_name)
    return versions[-1] if versions else None


def load_artifact(model_name: str, version: str | None = None) -> ModelArtifact | None:
    """Load an artifact's metadata. Returns ``None`` when absent.

    Callers must handle ``None`` explicitly; the platform never silently
    substitutes an untrained model for a requested trained one.
    """
    resolved = version or latest_version(model_name)
    if not resolved:
        return None
    directory = model_dir(model_name) / resolved
    metadata_path = directory / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text())
    except (ValueError, OSError):
        return None
    return ModelArtifact(model_name, resolved, directory, metadata)


def load_history(model_name: str, version: str | None = None) -> dict[str, Any] | None:
    artifact = load_artifact(model_name, version)
    if artifact is None or not artifact.history_path.exists():
        return None
    try:
        return json.loads(artifact.history_path.read_text())
    except (ValueError, OSError):
        return None


def registry_summary() -> dict[str, Any]:
    root = artifact_root()
    if not root.exists():
        return {"artifact_root": str(root), "models": []}
    models = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        versions = list_versions(entry.name)
        if not versions:
            continue
        models.append(
            {
                "model_name": entry.name,
                "versions": versions,
                "latest": latest_version(entry.name),
            }
        )
    return {"artifact_root": str(root), "models": models}
