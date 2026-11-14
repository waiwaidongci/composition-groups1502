"""Fallback executor used when no external worker is alive.

Runs are still claimed with a lease and published through the same artifact
protocol; running two executors at once cannot produce two results.
"""
import logging, os, socket, threading, time, uuid
from ..config.settings import (
    ARTIFACT_DIR, INLINE_RUNNER_ENABLED, WORKER_HEARTBEAT_SECONDS, WORKER_SWEEP_SECONDS,
)
from . import queue_service
from .recovery_service import sweep
from .runner_service import heartbeat, process

def worker_alive():
    from pathlib import Path
    try:
        stamp = float((Path(ARTIFACT_DIR) / "heartbeat").read_text())
        return time.time() - stamp < max(15, WORKER_HEARTBEAT_SECONDS * 3)
    except (OSError, ValueError):
        return False

class InlineRunner:
    def __init__(self):
        self.owner = f"{socket.gethostname()}:{os.getpid()}:inline:{uuid.uuid4().hex[:6]}"
        self.stopped = threading.Event()
        self.thread = None
        self.last_sweep = 0.0

    def start(self):
        if not INLINE_RUNNER_ENABLED or self.thread:
            return
        self.thread = threading.Thread(target=self._loop, name="inline-runner", daemon=True)
        self.thread.start()
        logging.info("inline recovery executor started as %s", self.owner)

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _loop(self):
        while not self.stopped.wait(1):
            if worker_alive():
                # A dedicated worker is publishing heartbeats: leave all runs to it.
                continue
            if time.monotonic() - self.last_sweep >= WORKER_SWEEP_SECONDS:
                try:
                    sweep(self.owner)
                except Exception:
                    logging.warning("inline recovery sweep failed", exc_info=True)
                # Separate file: the worker healthcheck must still notice a
                # missing worker even while this fallback is active.
                heartbeat("inline-heartbeat")
                self.last_sweep = time.monotonic()
            try:
                run_id = queue_service.take_run(timeout=1)
            except Exception:
                self.stopped.wait(2)
                continue
            if run_id is not None:
                process(run_id, self.owner)

inline_runner = InlineRunner()
