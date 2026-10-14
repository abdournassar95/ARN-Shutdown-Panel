import time

import pytest

from core.scheduler import Scheduler


def test_scheduler_countdown():
    finished = []
    ticks = []

    sched = Scheduler(
        on_tick=lambda st: ticks.append(st),
        on_finish=lambda a, f: finished.append((a, f)),
    )
    st = sched.start("shutdown", 1, False)
    assert st["action"] == "shutdown"
    assert st["remainingSecs"] == 1

    time.sleep(1.6)
    assert len(finished) == 1
    assert finished[0] == ("shutdown", False)
    assert sched.get_state() is None


def test_scheduler_warn_regression():
    """Regression: the warn callback used to crash the worker thread
    (UnboundLocalError on 'act'), so the countdown NEVER fired."""
    warns = []
    finished = []

    sched = Scheduler(
        on_finish=lambda a, f: finished.append((a, f)),
        on_warn=lambda remaining, action: warns.append((remaining, action)),
    )
    sched.set_warn_before(30)
    sched.start("shutdown", 1, False)

    time.sleep(1.6)
    assert len(warns) >= 1, "warn callback must fire (previously crashed the thread)"
    assert warns[0][1] == "shutdown"
    assert len(finished) == 1, "action must still fire after the warning"
    assert sched.get_state() is None


def test_scheduler_pause_resume():
    sched = Scheduler()
    sched.start("restart", 10, False)
    assert sched.get_state()["paused"] is False

    assert sched.pause() is True
    assert sched.get_state()["paused"] is True
    remaining = sched.get_state()["remainingSecs"]
    assert 8 <= remaining <= 10

    time.sleep(0.5)  # paused: nothing should fire
    assert sched.get_state() is not None

    assert sched.resume() is True
    assert sched.get_state()["paused"] is False

    assert sched.cancel() is True
    assert sched.get_state() is None


def test_scheduler_zero_delay_fires_immediately():
    finished = []
    sched = Scheduler(on_finish=lambda a, f: finished.append((a, f)))
    st = sched.start("lock", 0, True)
    assert st == {}  # no active state after immediate execution
    assert finished == [("lock", True)]


def test_scheduler_restart_overwrites_previous():
    finished = []
    sched = Scheduler(on_finish=lambda a, f: finished.append((a, f)))
    sched.start("shutdown", 5, False)
    sched.start("restart", 1, False)

    time.sleep(1.6)
    assert finished == [("restart", False)]
    assert sched.get_state() is None


def test_scheduler_stop():
    sched = Scheduler()
    sched.start("shutdown", 60, False)
    sched.stop()
    time.sleep(0.4)
    assert sched.get_state() is not None  # state kept, thread stopped


def test_scheduler_worker_reuse():
    """A single worker thread handles successive countdowns (no thread leak)."""
    sched = Scheduler()
    sched.start("lock", 1, False)
    t1 = sched._thread
    time.sleep(1.4)
    sched.start("lock", 1, False)
    t2 = sched._thread
    assert t1 is t2, "worker thread should be reused"
    time.sleep(1.4)
