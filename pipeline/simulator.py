"""Stage 1 — synthetic order intake (batch writes, live-feeling logs)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import Config, load_config
from pipeline.paths import ensure_data_dirs, raw_dir
from pipeline.runtime import run_polling_loop

RAW_COLUMNS = [
    "order_id",
    "timestamp",
    "distance_km",
    "prep_minutes",
    "order_value",
    "was_late",
]


def generate_batch(
    batch_size: int,
    seed: int | None = None,
    start_time: datetime | None = None,
) -> pd.DataFrame:
    """Create one batch of synthetic DashBite orders."""
    rng = np.random.default_rng(seed)
    now = start_time or datetime.now(timezone.utc)

    distance = rng.uniform(0.5, 12.0, size=batch_size)
    prep = rng.uniform(5.0, 45.0, size=batch_size)
    order_value = rng.uniform(8.0, 80.0, size=batch_size)

    # Simple label rule so training has a learnable signal
    late_prob = 1 / (1 + np.exp(-(0.35 * distance + 0.08 * prep - 4.0)))
    was_late = (rng.random(batch_size) < late_prob).astype(int)

    timestamps = [
        (now.timestamp() + i) for i in range(batch_size)
    ]
    iso_timestamps = [
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        for ts in timestamps
    ]

    return pd.DataFrame(
        {
            "order_id": [str(uuid.uuid4()) for _ in range(batch_size)],
            "timestamp": iso_timestamps,
            "distance_km": np.round(distance, 3),
            "prep_minutes": np.round(prep, 2),
            "order_value": np.round(order_value, 2),
            "was_late": was_late,
        }
    )


def corrupt_batch(
    df: pd.DataFrame,
    seed: int | None = None,
    row_frac: float = 0.3,
) -> pd.DataFrame:
    """Inject NaNs and wrong dtypes into a fraction of rows (demo dirty data)."""
    out = df.copy()
    n = len(out)
    if n == 0:
        return out

    # Allow mixed types in columns that we intentionally corrupt
    for col in ("distance_km", "prep_minutes", "order_value", "was_late", "timestamp"):
        out[col] = out[col].astype(object)

    rng = np.random.default_rng(seed)
    k = max(1, int(round(n * row_frac)))
    idx = rng.choice(n, size=min(k, n), replace=False)

    # Split corrupted rows: NaNs vs wrong types
    mid = max(1, len(idx) // 2)
    for i in idx[:mid]:
        out.at[i, "distance_km"] = np.nan
        out.at[i, "prep_minutes"] = np.nan
        out.at[i, "order_value"] = np.nan
    for i in idx[mid:]:
        out.at[i, "distance_km"] = "not_a_number"
        out.at[i, "was_late"] = "maybe"
        out.at[i, "timestamp"] = "NOT_A_TIMESTAMP"
        out.at[i, "prep_minutes"] = "ten"
    return out


def write_batch(df: pd.DataFrame, dest_dir: Path, tick: int = 0) -> Path:
    """Write a batch CSV into the raw landing zone."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = dest_dir / f"orders_{stamp}_{tick:04d}.csv"
    df.to_csv(path, index=False)
    return path


def run_once(cfg: Config | None = None, base: Path | None = None, tick: int = 0) -> Path:
    """Generate and write a single batch (one 'tick')."""
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    df = generate_batch(cfg.batch_size, seed=None)
    corrupted = False
    if np.random.random() < cfg.corrupt_batch_rate:
        df = corrupt_batch(df)
        corrupted = True
    path = write_batch(df, raw_dir(base), tick=tick)
    tag = " [corrupted]" if corrupted else ""
    print(f"new orders arrived ({len(df)} orders){tag} -> {path.name}")
    return path


def run_loop(cfg: Config | None = None, base: Path | None = None) -> None:
    """Continuously emit order batches (live-feeling feed)."""
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    tick = 0

    def step() -> None:
        nonlocal tick
        run_once(cfg=cfg, base=base, tick=tick)
        tick += 1

    run_polling_loop(
        step,
        cfg.poll_interval_seconds,
        "simulator",
        banner="DashBite order feed started",
    )


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
