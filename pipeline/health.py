"""Heartbeat files for liveness checks.

Each polling stage touches one file per stage in ``HEALTH_DIR``; the probe
``python -m pipeline.health <stage>`` exits 0 when that file is recent.

Standard library only, so the probe starts fast: do not import pandas,
scikit-learn or other pipeline modules here.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

__all__ = [
    "HEALTH_DIR_ENV",
    "MAX_AGE_ENV",
    "DEFAULT_MAX_AGE_SECONDS",
    "health_dir",
    "heartbeat_path",
    "write_heartbeat",
    "heartbeat_age",
    "max_age_seconds",
    "is_healthy",
    "main",
]


HEALTH_DIR_ENV = "HEALTH_DIR"
MAX_AGE_ENV = "HEALTH_MAX_AGE_SECONDS"
DEFAULT_MAX_AGE_SECONDS = 30.0


def health_dir() -> Path:
    """Return the heartbeat directory (default: <system temp dir>/dashbite-health).

    ``HEALTH_DIR`` follows the same rule as ``DATA_ROOT``: a leading ``~`` is
    expanded and a relative value raises ``ValueError``, because the stage and
    the probe would each resolve it against their own working directory.
    """
    env_dir = os.environ.get(HEALTH_DIR_ENV)
    if not env_dir:
        return Path(tempfile.gettempdir()) / "dashbite-health"
    # os.path.expanduser leaves "~" in place when there is no home to expand to.
    directory = Path(os.path.expanduser(env_dir))
    if not directory.is_absolute():
        raise ValueError(
            f"{HEALTH_DIR_ENV} must be an absolute path (a leading ~ is expanded), "
            f"got {env_dir!r}. A relative path would resolve against the working "
            "directory of each stage and of the probe."
        )
    return directory


def heartbeat_path(stage: str) -> Path:
    return health_dir() / f"{stage}.heartbeat"


def write_heartbeat(stage: str) -> Path:
    """Mark the stage as alive now."""
    path = heartbeat_path(stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def heartbeat_age(stage: str) -> float | None:
    """Seconds since the last heartbeat, or None if there is none."""
    try:
        mtime = heartbeat_path(stage).stat().st_mtime
    except FileNotFoundError:
        return None
    return time.time() - mtime


def max_age_seconds() -> float:
    return float(os.environ.get(MAX_AGE_ENV) or DEFAULT_MAX_AGE_SECONDS)


def is_healthy(stage: str, max_age: float | None = None) -> bool:
    """True when the stage's heartbeat is newer than ``max_age`` seconds."""
    age = heartbeat_age(stage)
    limit = max_age_seconds() if max_age is None else max_age
    return age is not None and age <= limit


def main(argv: list[str] | None = None) -> int:
    """Probe one stage. Exit code 0 is healthy, 1 is anything else."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m pipeline.health <stage>", file=sys.stderr)
        return 1
    stage = args[0]
    try:
        limit = max_age_seconds()
    except ValueError:
        print(f"unhealthy: {MAX_AGE_ENV} is not a number", file=sys.stderr)
        return 1
    try:
        age = heartbeat_age(stage)
    except ValueError as err:
        print(f"unhealthy: {err}", file=sys.stderr)
        return 1
    if age is None:
        print(f"unhealthy: no heartbeat for {stage} in {health_dir()}", file=sys.stderr)
        return 1
    if age > limit:
        print(
            f"unhealthy: {stage} heartbeat is {age:.1f}s old (max {limit:g}s)",
            file=sys.stderr,
        )
        return 1
    print(f"healthy: {stage} heartbeat is {age:.1f}s old (max {limit:g}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
