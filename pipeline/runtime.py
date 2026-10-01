"""Shared polling loop for the long-running stages, with graceful shutdown."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable

__all__ = ["STOP_SIGNALS", "run_polling_loop"]


STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def run_polling_loop(
    step: Callable[[], object],
    interval: float,
    stage: str,
    *,
    banner: str | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Call ``step`` every ``interval`` seconds until asked to stop.

    SIGTERM and SIGINT set the stop event: the current iteration finishes, the
    wait between iterations ends early, and the function returns so the process
    can exit 0. The handlers are installed before ``banner`` prints, so a signal
    sent once the banner is visible is never lost.

    Pass ``stop`` to control the loop directly (tests); no signal handlers are
    installed in that case.
    """
    previous: dict[int, object] = {}
    received: list[int] = []
    if stop is None:
        stop = threading.Event()

        def _request_stop(signum, frame) -> None:
            received.append(signum)
            stop.set()

        previous = {sig: signal.signal(sig, _request_stop) for sig in STOP_SIGNALS}

    try:
        if banner:
            print(banner)
        while not stop.is_set():
            step()
            stop.wait(interval)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    reason = signal.Signals(received[0]).name if received else "stop requested"
    print(f"{stage} stopped cleanly ({reason})")
