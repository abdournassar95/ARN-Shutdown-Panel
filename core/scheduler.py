"""
Precise deadline-based countdown scheduler (v2).
Single persistent worker thread with monotonic deadlines.
Emits ticks, warnings, and triggers command execution on deadline.
"""

import math
import threading
import time
from typing import Any, Callable, Dict, Optional


class Scheduler:
    """Manages a single active countdown with pause / resume / cancel semantics."""

    def __init__(
        self,
        on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_finish: Optional[Callable[[str, bool], None]] = None,
        on_warn: Optional[Callable[[int, str], None]] = None,
    ):
        self.on_tick = on_tick
        self.on_finish = on_finish
        self.on_warn = on_warn

        self.lock = threading.Lock()
        self.action: Optional[str] = None
        self.total_secs: int = 0
        self.remaining_secs: int = 0
        self.paused: bool = False
        self.force: bool = False
        self.deadline: float = 0.0
        self.started_at: int = 0
        self.warned: bool = False
        self.warn_before: int = 30

        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Worker thread (started once, reused for every countdown)
    # ------------------------------------------------------------------
    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker, daemon=True, name="ShutdownSchedulerThread"
            )
            self._thread.start()

    def _worker(self):
        while not self._stop_event.is_set():
            self._wake.wait(timeout=0.25)
            self._wake.clear()

            with self.lock:
                if self.action is None or self.paused:
                    continue

                now = time.monotonic()
                left = max(0, math.ceil(self.deadline - now))
                self.remaining_secs = left

                fire_action = False
                warn_user = False
                act: Optional[str] = None
                f = False

                if left <= 0:
                    act = self.action
                    f = self.force
                    self.action = None
                    self.remaining_secs = 0
                    fire_action = True
                elif (
                    self.warn_before > 0
                    and left <= self.warn_before
                    and not self.warned
                ):
                    self.warned = True
                    act = self.action
                    warn_user = True

            # Callbacks always run OUTSIDE the lock
            if fire_action:
                if self.on_tick:
                    self.on_tick({})
                if self.on_finish and act is not None:
                    self.on_finish(act, f)
            elif warn_user:
                if self.on_warn and act is not None:
                    self.on_warn(left, act)
                state = self.get_state()
                if state and self.on_tick:
                    self.on_tick(state)
            else:
                state = self.get_state()
                if state and self.on_tick:
                    self.on_tick(state)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_warn_before(self, seconds: int):
        with self.lock:
            self.warn_before = max(0, int(seconds))

    def get_state(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.action:
                return None
            # Live ETA that accounts for the remaining time (works while paused too)
            if self.paused:
                eta = int(time.time()) + self.remaining_secs
            else:
                eta = int(time.time()) + max(0, math.ceil(self.deadline - time.monotonic()))
            return {
                "action": self.action,
                "totalSecs": self.total_secs,
                "remainingSecs": self.remaining_secs,
                "paused": self.paused,
                "force": self.force,
                "startedAt": self.started_at,
                "endsAt": eta,
            }

    def start(
        self, action: str, delay_secs: int, force: bool = False
    ) -> Dict[str, Any]:
        with self.lock:
            self.action = action
            self.total_secs = max(0, int(delay_secs))
            self.remaining_secs = self.total_secs
            self.paused = False
            self.force = force
            self.deadline = time.monotonic() + self.total_secs
            self.started_at = int(time.time())
            self.warned = False
            immediate = self.total_secs == 0
            act, f = action, force

        if immediate:
            if self.on_tick:
                self.on_tick({})
            if self.on_finish:
                self.on_finish(act, f)
            return {}

        self._ensure_thread()
        self._wake.set()
        state = self.get_state() or {}
        if self.on_tick:
            self.on_tick(state)
        return state

    def pause(self) -> bool:
        with self.lock:
            if not self.action or self.paused:
                return False
            left = max(0, math.ceil(self.deadline - time.monotonic()))
            self.remaining_secs = left
            self.paused = True

        state = self.get_state()
        if state and self.on_tick:
            self.on_tick(state)
        return True

    def resume(self) -> bool:
        with self.lock:
            if not self.action or not self.paused:
                return False
            self.deadline = time.monotonic() + self.remaining_secs
            self.paused = False

        self._ensure_thread()
        self._wake.set()
        state = self.get_state()
        if state and self.on_tick:
            self.on_tick(state)
        return True

    def cancel(self) -> bool:
        with self.lock:
            if not self.action:
                return False
            self.action = None
            self.remaining_secs = 0
            self.paused = False

        if self.on_tick:
            self.on_tick({})
        return True

    def stop(self):
        """Stops the worker thread (used at application shutdown)."""
        self._stop_event.set()
        self._wake.set()
