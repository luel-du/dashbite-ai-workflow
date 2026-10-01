"""Stage 3 — train a tiny model when enough new labeled events arrive.

Independent write path: only writes checkpoints under data/models/.
Does not import or call inference.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from pipeline.config import Config, load_config
from pipeline.paths import ensure_data_dirs, features_dir, models_dir
from pipeline.runtime import run_polling_loop

STATE_FILENAME = "train_state.json"
FEATURE_COLUMNS = ["distance_km", "prep_minutes"]


def _state_path(base: Path | None = None) -> Path:
    return models_dir(base) / STATE_FILENAME


def load_state(base: Path | None = None) -> dict:
    path = _state_path(base)
    if not path.exists():
        return {"labeled_rows_at_last_train": 0, "last_checkpoint": None}
    return json.loads(path.read_text())


def save_state(state: dict, base: Path | None = None) -> None:
    ensure_data_dirs(base)
    _state_path(base).write_text(json.dumps(state, indent=2))


def load_all_features(base: Path | None = None) -> pd.DataFrame:
    fdir = features_dir(base)
    files = sorted(fdir.glob("features_*.csv"))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(p) for p in files]
    return pd.concat(frames, ignore_index=True)


def should_retrain(labeled_count: int, last_count: int, threshold: int) -> bool:
    """True when enough NEW labeled rows have arrived since last train."""
    return (labeled_count - last_count) >= threshold


def train_model(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    seed: int = 42,
) -> tuple[LogisticRegression, dict]:
    """Fit LogisticRegression and return model + metrics."""
    cols = feature_columns or FEATURE_COLUMNS
    clean = df.dropna(subset=cols + ["was_late"]).copy()
    if len(clean) < 4:
        raise ValueError("need at least 4 labeled rows to train")

    X = clean[cols]
    y = clean["was_late"].astype(int)

    model = LogisticRegression(max_iter=500, random_state=seed)

    # Prefer a held-out split when both classes have enough rows
    can_split = (
        y.nunique() >= 2
        and int(y.value_counts().min()) >= 2
        and len(clean) >= 8
    )
    if can_split:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=seed, stratify=y
        )
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        acc = float(accuracy_score(y_test, preds))
        return model, {
            "accuracy": acc,
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
        }

    model.fit(X, y)
    acc = float(accuracy_score(y, model.predict(X)))
    return model, {"accuracy": acc, "n_train": len(clean), "n_test": 0}


def write_checkpoint(
    model: LogisticRegression,
    metrics: dict,
    base: Path | None = None,
    stamp: str | None = None,
) -> Path:
    """Write a new timestamped checkpoint (never overwrite history)."""
    ensure_data_dirs(base)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ckpt_path = models_dir(base) / f"checkpoint_{stamp}.joblib"
    metrics_path = models_dir(base) / f"metrics_{stamp}.json"
    joblib.dump(
        {"model": model, "feature_columns": FEATURE_COLUMNS, "checkpoint_id": stamp},
        ckpt_path,
    )
    payload = {**metrics, "checkpoint_id": stamp, "feature_columns": FEATURE_COLUMNS}
    metrics_path.write_text(json.dumps(payload, indent=2))
    return ckpt_path


def maybe_train(cfg: Config | None = None, base: Path | None = None) -> Path | None:
    """Train if threshold met; return checkpoint path or None."""
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    df = load_all_features(base)
    if df.empty or "was_late" not in df.columns:
        return None

    labeled = df.dropna(subset=["was_late"])
    labeled_count = len(labeled)
    state = load_state(base)
    last = int(state.get("labeled_rows_at_last_train", 0))

    if not should_retrain(labeled_count, last, cfg.train_every_n_events):
        return None

    model, metrics = train_model(labeled, seed=cfg.random_seed)
    ckpt = write_checkpoint(model, metrics, base=base)
    state["labeled_rows_at_last_train"] = labeled_count
    state["last_checkpoint"] = ckpt.name
    save_state(state, base=base)
    print(
        f"trained checkpoint {ckpt.name} "
        f"(accuracy={metrics['accuracy']:.3f}, labeled={labeled_count})"
    )
    return ckpt


def run_loop(cfg: Config | None = None, base: Path | None = None) -> None:
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    run_polling_loop(
        lambda: maybe_train(cfg=cfg, base=base),
        cfg.poll_interval_seconds,
        "train",
        banner="DashBite training started (independent write path)",
    )


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
