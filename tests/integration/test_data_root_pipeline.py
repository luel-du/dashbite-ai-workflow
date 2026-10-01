"""Integration test — one pipeline pass driven only by DATA_ROOT."""

from __future__ import annotations

import pytest

from pipeline import infer, simulator
from pipeline.config import Config
from pipeline.preprocess import QUALITY_LOG, process_new_raw_files
from pipeline.train import STATE_FILENAME, maybe_train


@pytest.mark.integration
def test_one_pass_lands_all_output_under_env_data_root(monkeypatch, tmp_path):
    root = tmp_path / "store"
    monkeypatch.setenv("DATA_ROOT", str(root))
    # 40 clean rows: enough for both label classes and above the train threshold.
    cfg = Config(
        batch_size=40,
        train_every_n_events=5,
        corrupt_batch_rate=0.0,
        random_seed=42,
    )

    # No stage is given a base: the env var alone decides where data goes.
    raw_path = simulator.run_once(cfg=cfg)
    feature_paths = process_new_raw_files()
    ckpt_path = maybe_train(cfg=cfg)
    pred_path = infer.run_once(cfg=cfg)

    assert raw_path.parent == root / "raw"
    assert len(feature_paths) == 1
    assert feature_paths[0].parent == root / "features"
    assert (root / "quality" / QUALITY_LOG).is_file()
    assert ckpt_path is not None
    assert ckpt_path.parent == root / "models"
    assert (root / "models" / STATE_FILENAME).is_file()
    assert pred_path is not None
    assert pred_path.parent == root / "predictions"
    for path in (raw_path, feature_paths[0], ckpt_path, pred_path):
        assert path.is_file()

    # DATA_ROOT is the data directory itself, and nothing leaks beside it.
    assert not (root / "data").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["store"]
