"""Unit tests for the configurable data root (DATA_ROOT)."""

from __future__ import annotations

import pytest

from pipeline.paths import (
    DATA_SUBDIRS,
    PROJECT_ROOT,
    data_root,
    ensure_data_dirs,
    features_dir,
    models_dir,
    predictions_dir,
    quality_dir,
    raw_dir,
)


@pytest.mark.unit
def test_env_data_root_used_when_base_is_none(monkeypatch, tmp_path):
    root = tmp_path / "store"
    monkeypatch.setenv("DATA_ROOT", str(root))
    # DATA_ROOT is the data directory itself: no extra "data" level.
    assert data_root() == root
    assert raw_dir() == root / "raw"
    assert features_dir() == root / "features"
    assert models_dir() == root / "models"
    assert predictions_dir() == root / "predictions"
    assert quality_dir() == root / "quality"


@pytest.mark.unit
def test_env_data_root_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "first"))
    assert data_root() == tmp_path / "first"
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "second"))
    assert data_root() == tmp_path / "second"


@pytest.mark.unit
def test_explicit_base_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "from_env"))
    project = tmp_path / "project"
    # base is a project root: data lives in base/data.
    assert data_root(project) == project / "data"
    assert raw_dir(project) == project / "data" / "raw"


@pytest.mark.unit
def test_unset_env_keeps_project_default(monkeypatch):
    monkeypatch.delenv("DATA_ROOT", raising=False)
    assert data_root() == PROJECT_ROOT / "data"


@pytest.mark.unit
def test_empty_env_keeps_project_default(monkeypatch):
    monkeypatch.setenv("DATA_ROOT", "")
    assert data_root() == PROJECT_ROOT / "data"


@pytest.mark.unit
def test_env_data_root_expands_leading_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DATA_ROOT", "~/dash")
    assert data_root() == tmp_path / "dash"
    assert raw_dir() == tmp_path / "dash" / "raw"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    ["dash", "./dash", "../dash", "data", "~no_such_dashbite_user/dash"],
)
def test_relative_env_data_root_is_rejected(monkeypatch, value):
    monkeypatch.setenv("DATA_ROOT", value)
    with pytest.raises(ValueError, match="DATA_ROOT must be an absolute path") as err:
        data_root()
    # The message quotes the offending value so the fix is obvious.
    assert repr(value) in str(err.value)


@pytest.mark.unit
def test_relative_env_data_root_creates_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_ROOT", "dash")
    with pytest.raises(ValueError, match="DATA_ROOT must be an absolute path"):
        ensure_data_dirs()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_explicit_base_ignores_invalid_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", "dash")
    assert data_root(tmp_path) == tmp_path / "data"


@pytest.mark.unit
def test_ensure_data_dirs_creates_under_env_root(monkeypatch, tmp_path):
    root = tmp_path / "store"
    monkeypatch.setenv("DATA_ROOT", str(root))
    paths = ensure_data_dirs()
    assert set(paths) == set(DATA_SUBDIRS)
    for name, path in paths.items():
        assert path == root / name
        assert path.is_dir()
