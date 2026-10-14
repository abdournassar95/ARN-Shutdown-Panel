import time
from datetime import datetime, timedelta

from core.schedules import ScheduleEngine


def test_add_remove_toggle():
    eng = ScheduleEngine(on_fire=lambda s: None, check_interval=1)
    entry = eng.add("shutdown", "23:00", [0, 1, 2, 3, 4, 5, 6])
    assert entry["action"] == "shutdown"
    assert entry["time"] == "23:00"
    assert len(eng.snapshot()) == 1

    assert eng.toggle(entry["id"])["enabled"] is False
    assert eng.toggle(entry["id"])["enabled"] is True

    assert eng.remove(entry["id"]) is True
    assert eng.snapshot() == []


def test_sanitize_bad_values():
    eng = ScheduleEngine(on_fire=lambda s: None)
    entry = eng.add("explode", "99:99", [])
    assert entry["action"] == "shutdown"  # invalid action falls back
    assert entry["time"] == "23:00"  # invalid time falls back
    assert entry["days"] == list(range(7))  # empty days => every day


def test_engine_fires_at_time():
    fired = []
    eng = ScheduleEngine(on_fire=lambda s: fired.append(s), check_interval=0.2)

    # Schedule for the CURRENT minute — the engine should fire because
    # now_minutes == sched_minutes (exact match).
    now = datetime.now()
    # If we're near the end of the minute, wait for the next one
    if now.second >= 55:
        time.sleep(6)
        now = datetime.now()
    target = now.strftime("%H:%M")

    eng.add("shutdown", target, list(range(7)))
    eng.start()
    time.sleep(3.5)
    eng.stop()

    assert len(fired) == 1
    assert fired[0]["action"] == "shutdown"
    assert fired[0]["lastRun"] == datetime.now().date().isoformat()


def test_engine_no_double_fire():
    fired = []
    eng = ScheduleEngine(on_fire=lambda s: fired.append(s), check_interval=0.2)

    now = datetime.now()
    if now.second >= 55:
        time.sleep(6)
        now = datetime.now()
    target = now.strftime("%H:%M")

    eng.add("lock", target, list(range(7)))
    eng.start()
    time.sleep(4.5)
    eng.stop()

    assert len(fired) == 1, "same-day schedule must fire exactly once"


def test_engine_no_retroactive_fire():
    """REGRESSION: if the PC boots AFTER the scheduled time has passed,
    the schedule must NOT fire retroactively (previously it did >= comparison
    which caused immediate shutdown at boot)."""
    fired = []
    eng = ScheduleEngine(on_fire=lambda s: fired.append(s), check_interval=0.2)

    now = datetime.now()
    # Schedule for 2 hours AGO — must NOT fire
    past = now - timedelta(hours=2)
    target = past.strftime("%H:%M")

    eng.add("shutdown", target, list(range(7)))
    eng.start()
    time.sleep(1.5)
    eng.stop()

    assert fired == [], (
        "Schedule for a past time must NOT fire retroactively "
        "(would shut down PC at boot!)"
    )
    # But it must be marked as done so it doesn't try again later
    snap = eng.snapshot()
    assert snap[0]["lastRun"] == datetime.now().date().isoformat(), \
        "Missed schedule must be marked as lastRun=today"


def test_engine_day_filter():
    fired = []
    eng = ScheduleEngine(on_fire=lambda s: fired.append(s), check_interval=0.2)

    now = datetime.now()
    if now.second >= 55:
        time.sleep(6)
        now = datetime.now()
    target = now.strftime("%H:%M")

    # days use 0=Sunday: schedule for a day that is NOT today
    today_js = (now.weekday() + 1) % 7
    wrong_day = (today_js + 1) % 7

    eng.add("shutdown", target, [wrong_day])
    eng.start()
    time.sleep(3.0)
    eng.stop()

    assert fired == [], "schedule must not fire on the wrong weekday"
