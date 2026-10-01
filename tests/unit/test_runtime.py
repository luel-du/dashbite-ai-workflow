"""Unit tests for the shared polling loop (graceful shutdown)."""

from __future__ import annotations

import signal
import threading
import time

import pytest

from pipeline.runtime import STOP_SIGNALS, run_polling_loop

LONG_INTERVAL = 3600.0


@pytest.mark.unit
def test_loop_runs_step_until_stop_is_set():
    stop = threading.Event()
    calls: list[int] = []

    def step() -> None:
        calls.append(len(calls))
        if len(calls) == 3:
            stop.set()

    run_polling_loop(step, 0, "demo", stop=stop)
    assert calls == [0, 1, 2]


@pytest.mark.unit
def test_stop_during_step_skips_the_long_wait():
    stop = threading.Event()
    calls: list[int] = []

    def step() -> None:
        calls.append(1)
        stop.set()

    started = time.monotonic()
    run_polling_loop(step, LONG_INTERVAL, "demo", stop=stop)
    assert calls == [1]
    assert time.monotonic() - started < 5


@pytest.mark.unit
def test_stop_during_wait_returns_promptly():
    stop = threading.Event()
    calls: list[int] = []
    timer = threading.Timer(0.1, stop.set)
    timer.start()
    try:
        started = time.monotonic()
        run_polling_loop(lambda: calls.append(1), LONG_INTERVAL, "demo", stop=stop)
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()
    assert calls == [1]
    assert elapsed < 5


@pytest.mark.unit
def test_stop_already_set_never_runs_step():
    stop = threading.Event()
    stop.set()
    calls: list[int] = []
    run_polling_loop(lambda: calls.append(1), LONG_INTERVAL, "demo", stop=stop)
    assert calls == []


@pytest.mark.unit
def test_banner_prints_before_first_step_and_stop_message_after(capsys):
    stop = threading.Event()
    seen_at_step: list[str] = []

    def step() -> None:
        seen_at_step.append(capsys.readouterr().out)
        stop.set()

    run_polling_loop(step, LONG_INTERVAL, "demo", banner="demo started", stop=stop)
    assert seen_at_step == ["demo started\n"]
    assert capsys.readouterr().out == "demo stopped cleanly (stop requested)\n"


@pytest.mark.unit
@pytest.mark.parametrize("sig", STOP_SIGNALS, ids=lambda s: s.name)
def test_signal_finishes_the_iteration_then_stops(sig, capsys):
    before = {s: signal.getsignal(s) for s in STOP_SIGNALS}
    events: list[str] = []

    def step() -> None:
        # Handlers are in place before the banner, so they are by the first step.
        # Checked first: raising with the default handler would kill pytest.
        assert all(signal.getsignal(s) is not before[s] for s in STOP_SIGNALS)
        events.append("step started")
        signal.raise_signal(sig)
        events.append("step finished")

    started = time.monotonic()
    run_polling_loop(step, LONG_INTERVAL, "demo", banner="demo started")

    assert events == ["step started", "step finished"]
    assert time.monotonic() - started < 5
    assert f"demo stopped cleanly ({sig.name})" in capsys.readouterr().out
    # The previous handlers are restored once the loop returns.
    assert {s: signal.getsignal(s) for s in STOP_SIGNALS} == before
