"""Shared configuration for all pipeline stages."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# Project root: TestingAndContainerisationDemo/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    """Runtime settings. Override via environment variables."""

    train_every_n_events: int = 2000
    batch_size: int = 50
    poll_interval_seconds: float = 2.0
    feature_columns: tuple[str, ...] = ("distance_km", "prep_minutes")
    random_seed: int = 42
    # Fraction of batches that include corrupted rows (NaN / bad types)
    corrupt_batch_rate: float = 0.25

    @classmethod
    def from_env(cls) -> "Config":
        poll_raw = os.environ.get("POLL_INTERVAL_SECONDS", "2.0")
        poll_interval_seconds = float(poll_raw)
        # Zero or less would spin every stage without a pause between polls.
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError(
                "POLL_INTERVAL_SECONDS must be a positive, finite number, "
                f"got {poll_raw!r}"
            )
        return cls(
            train_every_n_events=int(
                os.environ.get("TRAIN_EVERY_N_EVENTS", "2000")
            ),
            batch_size=int(os.environ.get("BATCH_SIZE", "50")),
            poll_interval_seconds=poll_interval_seconds,
            random_seed=int(os.environ.get("RANDOM_SEED", "42")),
            corrupt_batch_rate=float(
                os.environ.get("CORRUPT_BATCH_RATE", "0.25")
            ),
        )

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = Config()


def load_config() -> Config:
    """Load config from environment, falling back to defaults."""
    return Config.from_env()
