"""Unit tests for heartbeat files and the health probe CLI."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from pipeline import health
from pipeline.paths import PROJECT_ROOT


@pytest.fixture(autouse=True)
def health_home(monkeypatch, tmp_path):
    """Every test gets its own HEALTH_DIR and the default threshold."""
    directory = tmp_path / "health"
    monkeypatch.setenv("HEALTH_DIR", str(directory))
    monkeypatch.delenv("HEALTH_MAX_AGE_SECONDS", raising=False)
    return directory


def _age(stage: str, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(health.heartbeat_path(stage), (old, old))


@pytest.mark.unit
def test_fresh_heartbeat_is_healthy(health_home):
    path = health.write_heartbeat("simulator")
    assert path == health_home / "simulator.heartbeat"
    assert path.is_file()
    assert health.is_healthy("simulator")


@pytest.mark.unit
def test_aged_heartbeat_is_unhealthy():
    health.write_heartbeat("simulator")
    _age("simulator", health.DEFAULT_MAX_AGE_SECONDS + 5)
    assert not health.is_healthy("simulator")


@pytest.mark.unit
def test_missing_heartbeat_is_unhealthy(health_home):
    assert health.heartbeat_age("simulator") is None
    assert not health.is_healthy("simulator")
    # Probing must not create anything.
    assert not health_home.exists()


@pytest.mark.unit
def test_write_refreshes_an_aged_heartbeat():
    health.write_heartbeat("train")
    _age("train", 120)
    assert not health.is_healthy("train")
    health.write_heartbeat("train")
    assert health.is_healthy("train")


@pytest.mark.unit
def test_one_heartbeat_file_per_stage():
    health.write_heartbeat("simulator")
    assert health.is_healthy("simulator")
    assert not health.is_healthy("train")


@pytest.mark.unit
def test_max_age_comes_from_env_at_call_time(monkeypatch):
    health.write_heartbeat("infer")
    _age("infer", 45)
    assert not health.is_healthy("infer")
    monkeypatch.setenv("HEALTH_MAX_AGE_SECONDS", "60")
    assert health.is_healthy("infer")
    monkeypatch.setenv("HEALTH_MAX_AGE_SECONDS", "10")
    assert not health.is_healthy("infer")
    # An explicit max_age wins over the environment.
    assert health.is_healthy("infer", max_age=100)


@pytest.mark.unit
def test_health_dir_default_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HEALTH_DIR", str(tmp_path / "elsewhere"))
    assert health.health_dir() == tmp_path / "elsewhere"
    monkeypatch.delenv("HEALTH_DIR")
    assert health.health_dir() == Path(tempfile.gettempdir()) / "dashbite-health"


@pytest.mark.unit
def test_health_dir_expands_leading_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HEALTH_DIR", "~/beats")
    assert health.health_dir() == tmp_path / "beats"
    assert health.write_heartbeat("simulator") == tmp_path / "beats" / "simulator.heartbeat"
    assert health.is_healthy("simulator")


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    ["beats", "./beats", "../beats", "~no_such_dashbite_user/beats"],
)
def test_relative_health_dir_is_rejected(monkeypatch, value):
    monkeypatch.setenv("HEALTH_DIR", value)
    with pytest.raises(ValueError, match="HEALTH_DIR must be an absolute path") as err:
        health.health_dir()
    assert repr(value) in str(err.value)


@pytest.mark.unit
def test_relative_health_dir_creates_nothing_and_probe_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEALTH_DIR", "beats")
    with pytest.raises(ValueError, match="HEALTH_DIR must be an absolute path"):
        health.write_heartbeat("simulator")
    assert list(tmp_path.iterdir()) == []
    # The probe reports the problem instead of raising.
    assert health.main(["simulator"]) == 1
    assert "HEALTH_DIR must be an absolute path" in capsys.readouterr().err


@pytest.mark.unit
def test_cli_exit_codes(capsys):
    assert health.main(["simulator"]) == 1  # missing
    assert "no heartbeat for simulator" in capsys.readouterr().err

    health.write_heartbeat("simulator")
    assert health.main(["simulator"]) == 0  # fresh
    assert capsys.readouterr().out.startswith("healthy: simulator")

    _age("simulator", health.DEFAULT_MAX_AGE_SECONDS + 5)
    assert health.main(["simulator"]) == 1  # aged
    assert "unhealthy: simulator heartbeat" in capsys.readouterr().err


@pytest.mark.unit
def test_cli_bad_usage_and_bad_threshold_exit_1(monkeypatch, capsys):
    assert health.main([]) == 1
    assert health.main(["simulator", "train"]) == 1
    assert "usage" in capsys.readouterr().err

    health.write_heartbeat("simulator")
    monkeypatch.setenv("HEALTH_MAX_AGE_SECONDS", "soon")
    assert health.main(["simulator"]) == 1
    assert "not a number" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_threshold_must_be_positive_and_finite(monkeypatch, capsys, value):
    # nan and inf used to make a heartbeat of any age count as fresh.
    health.write_heartbeat("simulator")
    _age("simulator", 7200)
    monkeypatch.setenv("HEALTH_MAX_AGE_SECONDS", value)

    assert health.main(["simulator"]) == 1
    err = capsys.readouterr().err
    assert "HEALTH_MAX_AGE_SECONDS must be a positive, finite number" in err
    assert repr(value) in err

    # The function and the probe agree: neither reports healthy.
    with pytest.raises(ValueError, match="must be a positive, finite number"):
        health.is_healthy("simulator")


@pytest.mark.unit
def test_probe_and_is_healthy_agree_on_valid_thresholds(monkeypatch):
    health.write_heartbeat("simulator")
    _age("simulator", 45)
    for value, expected in (("60", True), ("10", False), (" 60 ", True), ("1e9", True)):
        monkeypatch.setenv("HEALTH_MAX_AGE_SECONDS", value)
        assert health.is_healthy("simulator") is expected
        assert health.main(["simulator"]) == (0 if expected else 1)


@pytest.mark.unit
def test_probe_command_exit_codes(health_home):
    """The command the Compose health check runs: python -m pipeline.health <stage>."""

    def probe(stage: str) -> int:
        return subprocess.run(
            [sys.executable, "-m", "pipeline.health", stage],
            cwd=PROJECT_ROOT,
            env={**os.environ, "HEALTH_DIR": str(health_home)},
            capture_output=True,
            timeout=60,
        ).returncode

    health.write_heartbeat("preprocess")
    assert probe("preprocess") == 0
    assert probe("train") == 1


@pytest.mark.unit
def test_health_module_imports_only_the_standard_library(health_home):
    heavy = ("numpy", "pandas", "sklearn", "joblib", "streamlit")
    code = (
        "import sys, pipeline.health; "
        f"print(','.join(m for m in {heavy!r} if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env={**os.environ, "HEALTH_DIR": str(health_home)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
