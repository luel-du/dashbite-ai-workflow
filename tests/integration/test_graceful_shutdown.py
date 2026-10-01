"""Integration test — each stage exits 0 on SIGTERM instead of being killed."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from pipeline.paths import PROJECT_ROOT

STAGE_BANNERS = {
    "simulator": "DashBite order feed started",
    "preprocess": "DashBite preprocess started",
    "train": "DashBite training started",
    "infer": "DashBite inference started",
}

STARTUP_TIMEOUT = 60  # imports (pandas, scikit-learn) dominate
SHUTDOWN_TIMEOUT = 5


@pytest.mark.integration
@pytest.mark.parametrize("stage", STAGE_BANNERS)
def test_stage_exits_zero_on_sigterm(stage, tmp_path):
    banner = STAGE_BANNERS[stage]
    log = tmp_path / f"{stage}.log"
    env = {
        **os.environ,
        "DATA_ROOT": str(tmp_path / "data"),
        "HEALTH_DIR": str(tmp_path / "health"),
        "PYTHONUNBUFFERED": "1",
        # Far longer than SHUTDOWN_TIMEOUT: only an interrupted wait can pass.
        "POLL_INTERVAL_SECONDS": "30",
    }
    with log.open("w") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", f"pipeline.{stage}"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    try:
        # The stop handlers are installed before the banner prints, so once the
        # banner is visible the signal cannot be lost.
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while banner not in log.read_text():
            assert proc.poll() is None, f"{stage} exited early:\n{log.read_text()}"
            assert time.monotonic() < deadline, f"no banner from {stage}:\n{log.read_text()}"
            time.sleep(0.05)

        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"{stage} still running {SHUTDOWN_TIMEOUT}s after SIGTERM:\n{log.read_text()}"
            )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    output = log.read_text()
    assert returncode == 0, output
    assert f"{stage} stopped cleanly (SIGTERM)" in output
