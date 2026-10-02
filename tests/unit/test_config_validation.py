"""Unit tests for validation of environment-driven config."""

from __future__ import annotations

import pytest

from pipeline.config import DEFAULT_CONFIG, load_config


@pytest.mark.unit
@pytest.mark.parametrize("value", ["0", "0.0", "-1", "nan", "inf"])
def test_poll_interval_must_be_positive_and_finite(monkeypatch, value):
    # Zero or less would spin every stage without a pause between polls.
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", value)
    with pytest.raises(ValueError, match="POLL_INTERVAL_SECONDS must be a positive") as err:
        load_config()
    # The message quotes the offending value so the fix is obvious.
    assert repr(value) in str(err.value)


@pytest.mark.unit
@pytest.mark.parametrize("value, expected", [("0.5", 0.5), ("2", 2.0), ("30", 30.0)])
def test_positive_poll_interval_is_accepted(monkeypatch, value, expected):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", value)
    assert load_config().poll_interval_seconds == expected


@pytest.mark.unit
def test_unset_poll_interval_keeps_the_default(monkeypatch):
    monkeypatch.delenv("POLL_INTERVAL_SECONDS", raising=False)
    assert load_config().poll_interval_seconds == DEFAULT_CONFIG.poll_interval_seconds
