"""
Weekly schedule engine: fires actions at configured times/days (cron-lite).
Example: shutdown every day at 23:00, restart every Friday at 02:00.
"""

import threading
import uuid
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

VALID_ACTIONS = {
    "shutdown",
    "restart",
    "sleep",
    "hibernate",
    "display_off",
    "lock",
    "signout",
}


class ScheduleEngine:
    """Background thread that checks schedules every N seconds and fires actions."""

    def __init__(
        self,
        on_fire: Callable[[Dict[str, Any]], None],
        check_interval: float = 20.0,
    ):
        self.on_fire = on_fire
        self.check_interval = check_interval
        self.lock = threading.Lock()
        self.schedules: List[Dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def load(self, schedules: List[Dict[str, Any]]):
        with self.lock:
            self.schedules = [self._sanitize(s) for s in (schedules or [])]

    def snapshot(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(s) for s in self.schedules]

    @staticmethod
    def _sanitize(s: Dict[str, Any]) -> Dict[str, Any]:
        action = str(s.get("action", "shutdown"))
        if action not in VALID_ACTIONS:
            # Never silently downgrade an unsupported action to shutdown:
            # "display_off" used to become a full power-off this way.
            from core.app_logger import get_logger

            get_logger().warning(
                "Unknown schedule action %r; falling back to 'shutdown'", action
            )
            action = "shutdown"
        time_str = str(s.get("time", "23:00"))
        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            time_str = "23:00"
        days = s.get("days", list(range(7)))
        if not isinstance(days, list):
            days = list(range(7))
        days = sorted({int(d) % 7 for d in days if isinstance(d, (int, float))})
        if not days:
            days = list(range(7))
        return {
            "id": str(s.get("id") or uuid.uuid4().hex[:8]),
            "action": action,
            "time": time_str,
            "days": days,
            "enabled": bool(s.get("enabled", True)),
            "lastRun": s.get("lastRun") or "",
        }

    def add(self, action: str, time_str: str, days: List[int], enabled: bool = True) -> Dict[str, Any]:
        entry = self._sanitize(
            {"action": action, "time": time_str, "days": days, "enabled": enabled}
        )
        with self.lock:
            self.schedules.append(entry)
        return entry

    def remove(self, schedule_id: str) -> bool:
        with self.lock:
            before = len(self.schedules)
            self.schedules = [s for s in self.schedules if s["id"] != schedule_id]
            return len(self.schedules) < before

    def toggle(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            for s in self.schedules:
                if s["id"] == schedule_id:
                    s["enabled"] = not s["enabled"]
                    return dict(s)
        return None

    # ------------------------------------------------------------------
    # Engine loop
    # ------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ScheduleEngineThread"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._check_once()
            except Exception:
                pass
            self._stop.wait(self.check_interval)

    def _check_once(self):
        now = datetime.now()
        today = date.today().isoformat()
        now_minutes = now.hour * 60 + now.minute

        with self.lock:
            due = []
            for s in self.schedules:
                if not s["enabled"] or s["lastRun"] == today:
                    continue
                # Stored days use 0=Sunday (JS getDay); Python weekday() uses 0=Monday.
                if (now.weekday() + 1) % 7 not in s["days"]:
                    continue
                try:
                    h, m = (int(x) for x in s["time"].split(":"))
                except Exception:
                    continue
                sched_minutes = h * 60 + m
                # Fire only when the current minute matches (tight window).
                # The check_interval (~20s) guarantees we hit once per minute.
                # If the PC boots AFTER the scheduled time, we must NOT fire
                # retroactively — mark it as done so it doesn't fire later today
                # either (e.g. if boot is 09:00 and schedule was 03:00).
                if now_minutes == sched_minutes:
                    s["lastRun"] = today
                    due.append(dict(s))
                elif now_minutes > sched_minutes:
                    # Missed window: mark done to prevent late-firing today.
                    s["lastRun"] = today

        for s in due:
            try:
                self.on_fire(s)
            except Exception:
                pass
