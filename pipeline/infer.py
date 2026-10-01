"""Stage 4 — score new feature rows with the newest checkpoint.

Independent read path: only reads data/models/. Does not import or call train.
"""

from __future__ import annotations

import time
from pathlib import Path

import joblib
import pandas as pd

from pipeline.config import Config, load_config
from pipeline.paths import ensure_data_dirs, features_dir, models_dir, predictions_dir
from pipeline.runtime import run_polling_loop

FEATURE_COLUMNS = ["distance_km", "prep_minutes"]


def list_checkpoints(base: Path | None = None) -> list[Path]:
    mdir = models_dir(base)
    return sorted(mdir.glob("checkpoint_*.joblib"))


def newest_checkpoint(base: Path | None = None) -> Path | None:
    """Return the most recent checkpoint by filename (timestamp in name)."""
    ckpts = list_checkpoints(base)
    if not ckpts:
        return None
    # Filenames are checkpoint_YYYYMMDD_HHMMSS.joblib — lexicographic == chronological
    return ckpts[-1]


def load_checkpoint(path: Path) -> dict:
    return joblib.load(path)


def load_all_features(base: Path | None = None) -> pd.DataFrame:
    fdir = features_dir(base)
    files = sorted(fdir.glob("features_*.csv"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(p) for p in files], ignore_index=True)


def load_existing_predictions(base: Path | None = None) -> pd.DataFrame:
    pdir = predictions_dir(base)
    files = sorted(pdir.glob("predictions_*.csv"))
    if not files:
        return pd.DataFrame(columns=["order_id"])
    return pd.concat([pd.read_csv(p) for p in files], ignore_index=True)


def score_frame(df: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    """Score rows with a loaded checkpoint bundle."""
    model = bundle["model"]
    cols = list(bundle.get("feature_columns", FEATURE_COLUMNS))
    checkpoint_id = bundle.get("checkpoint_id", "unknown")
    X = df[cols]
    proba = model.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    return pd.DataFrame(
        {
            "order_id": df["order_id"].values,
            "late_probability": proba.round(4),
            "predicted_late": pred,
            "checkpoint_id": checkpoint_id,
        }
    )


def run_once(
    cfg: Config | None = None,
    base: Path | None = None,
    _warned_no_ckpt: list[bool] | None = None,
) -> Path | None:
    """Score unscored feature rows with the newest checkpoint."""
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    warned = _warned_no_ckpt if _warned_no_ckpt is not None else [False]

    ckpt_path = newest_checkpoint(base)
    if ckpt_path is None:
        if not warned[0]:
            print("no checkpoint available yet — waiting")
            warned[0] = True
        return None

    bundle = load_checkpoint(ckpt_path)
    features = load_all_features(base)
    if features.empty:
        return None

    existing = load_existing_predictions(base)
    scored_ids = set(existing["order_id"].astype(str)) if not existing.empty else set()
    pending = features[~features["order_id"].astype(str).isin(scored_ids)].copy()
    if pending.empty:
        return None

    preds = score_frame(pending, bundle)
    out = predictions_dir(base) / f"predictions_{ckpt_path.stem}_{int(time.time())}.csv"
    preds.to_csv(out, index=False)
    print(f"scored {len(preds)} orders with {ckpt_path.name} -> {out.name}")
    return out


def run_loop(cfg: Config | None = None, base: Path | None = None) -> None:
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    warned = [False]
    loaded_name: str | None = None

    def step() -> None:
        nonlocal loaded_name
        ckpt = newest_checkpoint(base)
        if ckpt is not None and ckpt.name != loaded_name:
            print(f"using checkpoint {ckpt.name}")
            loaded_name = ckpt.name
            warned[0] = False
        run_once(cfg=cfg, base=base, _warned_no_ckpt=warned)

    run_polling_loop(
        step,
        cfg.poll_interval_seconds,
        "infer",
        banner="DashBite inference started (independent read path)",
    )


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
