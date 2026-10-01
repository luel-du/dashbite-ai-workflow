"""Stage 2 — clean raw orders, derive features, log field failures + throughput."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.config import Config, load_config
from pipeline.paths import ensure_data_dirs, features_dir, quality_dir, raw_dir
from pipeline.runtime import run_polling_loop

REQUIRED_COLUMNS = [
    "order_id",
    "timestamp",
    "distance_km",
    "prep_minutes",
    "order_value",
    "was_late",
]

NUMERIC_COLUMNS = ["distance_km", "prep_minutes", "order_value"]
PEAK_HOURS = {11, 12, 13, 17, 18, 19}
QUALITY_LOG = "batch_quality.csv"


def coerce_types(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Coerce columns to expected types; count NaN + type failures per field."""
    out = df.copy()
    failures = {col: 0 for col in REQUIRED_COLUMNS}

    for col in REQUIRED_COLUMNS:
        if col not in out.columns:
            failures[col] = len(out)
            out[col] = pd.NA

    # Existing nulls
    for col in REQUIRED_COLUMNS:
        failures[col] += int(out[col].isna().sum())

    for col in NUMERIC_COLUMNS:
        before_ok = out[col].notna()
        coerced = pd.to_numeric(out[col], errors="coerce")
        type_fail = before_ok & coerced.isna()
        failures[col] += int(type_fail.sum())
        out[col] = coerced

    before_ok = out["was_late"].notna()
    coerced_late = pd.to_numeric(out["was_late"], errors="coerce")
    type_fail = before_ok & coerced_late.isna()
    failures["was_late"] += int(type_fail.sum())
    out["was_late"] = coerced_late

    before_ok = out["timestamp"].notna()
    coerced_ts = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    type_fail = before_ok & coerced_ts.isna()
    failures["timestamp"] += int(type_fail.sum())
    out["timestamp"] = coerced_ts

    # order_id: empty string counts as failure
    bad_id = out["order_id"].isna() | (out["order_id"].astype(str).str.strip() == "")
    failures["order_id"] += int((bad_id & out["order_id"].notna()).sum()) if "order_id" in df.columns else 0

    return out, failures


def drop_invalid(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with missing/invalid values (expects coerced types when possible)."""
    out, _ = coerce_types(df)
    out = out.dropna(subset=REQUIRED_COLUMNS)
    out = out[out["distance_km"] > 0]
    out = out[out["prep_minutes"] > 0]
    out = out[out["order_value"] > 0]
    out = out[out["was_late"].isin([0, 1])]
    out = out.reset_index(drop=True)
    # Keep timestamps as ISO strings for stable CSV / regression fixtures
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).map(
        lambda t: t.isoformat()
    )
    out["was_late"] = out["was_late"].astype(int)
    return out


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add hour and is_peak from timestamp."""
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    mask = ~ts.isna()
    out = out.loc[mask].copy()
    ts = ts.loc[mask]
    out["hour"] = ts.dt.hour.astype(int)
    out["is_peak"] = out["hour"].isin(PEAK_HOURS).astype(int)
    return out.reset_index(drop=True)


def preprocess_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Full preprocess: drop invalid then add features."""
    return add_features(drop_invalid(df))


def preprocess_with_quality(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Preprocess and return features plus a quality/throughput record."""
    rows_in = len(df)
    _, field_failures = coerce_types(df)
    features = preprocess_frame(df)
    rows_out = len(features)
    record = {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped": rows_in - rows_out,
        "drop_rate": (rows_in - rows_out) / rows_in if rows_in else 0.0,
        **{f"fail_{k}": int(v) for k, v in field_failures.items()},
    }
    return features, record


def _processed_marker(raw_path: Path, feat_dir: Path) -> Path:
    return feat_dir / f".done_{raw_path.name}"


def _append_quality_log(record: dict, base: Path | None = None) -> Path:
    qdir = quality_dir(base)
    qdir.mkdir(parents=True, exist_ok=True)
    path = qdir / QUALITY_LOG
    row = pd.DataFrame([record])
    if path.exists():
        row.to_csv(path, mode="a", header=False, index=False)
    else:
        row.to_csv(path, index=False)
    return path


def process_new_raw_files(base: Path | None = None) -> list[Path]:
    """Convert unprocessed raw CSVs into feature CSVs; log quality per batch."""
    ensure_data_dirs(base)
    rdir = raw_dir(base)
    fdir = features_dir(base)
    written: list[Path] = []

    for raw_path in sorted(rdir.glob("orders_*.csv")):
        marker = _processed_marker(raw_path, fdir)
        if marker.exists():
            continue
        df = pd.read_csv(raw_path)
        features, quality = preprocess_with_quality(df)
        quality["batch_file"] = raw_path.name
        quality["processed_at"] = datetime.now(timezone.utc).isoformat()
        out_path = fdir / f"features_{raw_path.stem}.csv"
        features.to_csv(out_path, index=False)
        _append_quality_log(quality, base=base)
        marker.write_text(raw_path.name)
        written.append(out_path)
        print(
            f"preprocessed {raw_path.name} -> {out_path.name} "
            f"({quality['rows_out']}/{quality['rows_in']} rows kept, "
            f"drop_rate={quality['drop_rate']:.1%})"
        )
    return written


def run_loop(cfg: Config | None = None, base: Path | None = None) -> None:
    cfg = cfg or load_config()
    ensure_data_dirs(base)
    run_polling_loop(
        lambda: process_new_raw_files(base=base),
        cfg.poll_interval_seconds,
        "preprocess",
        banner="DashBite preprocess started",
    )


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
