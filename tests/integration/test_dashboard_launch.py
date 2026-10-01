"""Integration test — the dashboard imports the way `streamlit run` launches it.

`streamlit run` puts only the script's folder on sys.path, never the working
directory, so `pipeline` must be importable from the environment (PYTHONPATH).
This has to stay a subprocess: a child inherits environment variables but not
pytest's sys.path (`pythonpath = .` in pytest.ini), and `-P` keeps the working
directory off the path. Run it through `make test`, which sets PYTHONPATH.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from pipeline.paths import PROJECT_ROOT


@pytest.mark.integration
def test_dashboard_imports_without_cwd_on_sys_path(tmp_path):
    result = subprocess.run(
        [sys.executable, "-P", "-c", "import pipeline.dashboard.app"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATA_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
