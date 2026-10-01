"""Streamlit dashboards: Model Pulse (ML) and Ops Control (business)."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline.dashboard.biz_metrics import at_risk_order_value, late_rate
from pipeline.dashboard.ml_metrics import sample_volume, score_summary
from pipeline.dashboard.quality_metrics import field_failure_totals, throughput_summary
from pipeline.paths import features_dir, predictions_dir, quality_dir
from pipeline.preprocess import QUALITY_LOG


def _load_csvs(directory: Path, pattern: str) -> pd.DataFrame:
    files = sorted(directory.glob(pattern))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(p) for p in files], ignore_index=True)


def load_features(base: Path | None = None) -> pd.DataFrame:
    return _load_csvs(features_dir(base), "features_*.csv")


def load_predictions(base: Path | None = None) -> pd.DataFrame:
    return _load_csvs(predictions_dir(base), "predictions_*.csv")


def load_quality_log(base: Path | None = None) -> pd.DataFrame:
    path = quality_dir(base) / QUALITY_LOG
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def main() -> None:
    st.set_page_config(page_title="DashBite", layout="wide")
    st.title("DashBite")

    page = st.sidebar.radio("Page", ["Model Pulse", "Ops Control"])
    auto = st.sidebar.checkbox("Auto-refresh (2s)", value=True)
    base = None  # resolve via DATA_ROOT, else <project>/data
    features = load_features(base)
    predictions = load_predictions(base)
    quality = load_quality_log(base)
    throughput = throughput_summary(quality)
    failures = field_failure_totals(quality)

    if page == "Model Pulse":
        st.header("Model Pulse")
        st.caption("Samples, model outputs, throughput, and field-level failures")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sample volume", sample_volume(features))
        c2.metric("Batches processed", throughput["batches"])
        c3.metric("Rows in / out", f"{throughput['rows_in']} / {throughput['rows_out']}")
        c4.metric("Drop rate", f"{throughput['drop_rate']:.1%}")

        summary = score_summary(predictions)
        st.metric("Mean late probability", f"{summary['mean_probability']:.3f}")

        st.subheader("Field-level failures")
        if failures:
            fail_df = pd.DataFrame(
                {"field": list(failures.keys()), "failures": list(failures.values())}
            ).set_index("field")
            st.bar_chart(fail_df)
            st.dataframe(fail_df, use_container_width=True)
        else:
            st.info("No quality log yet — waiting for preprocess.")

        st.subheader("Batch throughput (recent)")
        if not quality.empty and "rows_in" in quality.columns:
            recent = quality.tail(30).copy()
            chart_cols = [c for c in ("rows_in", "rows_out", "rows_dropped") if c in recent.columns]
            st.line_chart(recent[chart_cols])
        else:
            st.info("No batch throughput yet.")

        if not predictions.empty and "late_probability" in predictions.columns:
            st.subheader("Score distribution")
            st.bar_chart(predictions["late_probability"].value_counts(bins=10).sort_index())
        else:
            st.info("No predictions yet.")
    else:
        st.header("Ops Control")
        st.caption("Business view of late risk")
        rate = late_rate(features)
        risk = at_risk_order_value(features, predictions)
        st.metric("Late rate", f"{rate:.1%}")
        st.metric("Orders at risk (value)", f"${risk:,.2f}")
        st.metric("Throughput (rows kept)", throughput["rows_out"])
        if not predictions.empty:
            st.subheader("Recent predictions")
            st.dataframe(predictions.tail(50), use_container_width=True)
        else:
            st.info("No predictions yet.")

    if auto:
        time.sleep(2)
        st.rerun()


if __name__ == "__main__":
    main()
