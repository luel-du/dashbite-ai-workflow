"""Data directory helpers shared by every stage."""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.config import PROJECT_ROOT

__all__ = [
    "PROJECT_ROOT",
    "DATA_ROOT_ENV",
    "DATA_SUBDIRS",
    "data_root",
    "raw_dir",
    "features_dir",
    "models_dir",
    "predictions_dir",
    "quality_dir",
    "ensure_data_dirs",
]


DATA_ROOT_ENV = "DATA_ROOT"
DATA_SUBDIRS = ("raw", "features", "models", "predictions", "quality")


def data_root(base: Path | None = None) -> Path:
    """Return the data root.

    An explicit ``base`` is a project root and wins: data lives in ``base/data``.
    Otherwise the ``DATA_ROOT`` environment variable, read at call time, is the
    data directory itself. Unset (or empty) keeps the default ``<project>/data``.

    ``DATA_ROOT`` must be absolute once a leading ``~`` is expanded. A relative
    value raises ``ValueError``: every stage would resolve it against its own
    working directory and the stages could silently stop sharing data.
    """
    if base is not None:
        return base / "data"
    env_root = os.environ.get(DATA_ROOT_ENV)
    if not env_root:
        return PROJECT_ROOT / "data"
    # os.path.expanduser leaves "~" in place when there is no home to expand to.
    root = Path(os.path.expanduser(env_root))
    if not root.is_absolute():
        raise ValueError(
            f"{DATA_ROOT_ENV} must be an absolute path (a leading ~ is expanded), "
            f"got {env_root!r}. A relative path would resolve against each "
            "stage's working directory."
        )
    return root


def raw_dir(base: Path | None = None) -> Path:
    return data_root(base) / "raw"


def features_dir(base: Path | None = None) -> Path:
    return data_root(base) / "features"


def models_dir(base: Path | None = None) -> Path:
    return data_root(base) / "models"


def predictions_dir(base: Path | None = None) -> Path:
    return data_root(base) / "predictions"


def quality_dir(base: Path | None = None) -> Path:
    return data_root(base) / "quality"


def ensure_data_dirs(base: Path | None = None) -> dict[str, Path]:
    """Create the standard data folders and return their paths."""
    root = data_root(base)
    paths = {name: root / name for name in DATA_SUBDIRS}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
