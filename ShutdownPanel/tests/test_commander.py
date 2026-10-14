import sys

from core.commander import Commander


def test_windows_shutdown_planning():
    plan = Commander.plan("shutdown", delay_secs=0, force=False)
    assert plan["supported"] is True
    if sys.platform == "win32":
        assert plan["program"] == "shutdown.exe"
        assert "/s" in plan["args"]
        assert "/t" in plan["args"]
        assert "0" in plan["args"]
        assert "/f" not in plan["args"]


def test_windows_restart_force():
    plan = Commander.plan("restart", delay_secs=60, force=True)
    assert plan["supported"] is True
    if sys.platform == "win32":
        assert plan["program"] == "shutdown.exe"
        assert "/r" in plan["args"]
        assert "/t" in plan["args"]
        assert "60" in plan["args"]
        assert "/f" in plan["args"]


def test_safe_host_validation():
    assert Commander.is_safe_host("192.168.1.100") is True
    assert Commander.is_safe_host("laptop-ahmed") is True
    assert Commander.is_safe_host("host;calc.exe") is False
    assert Commander.is_safe_host("10.0.0.1 /f") is False
    assert Commander.is_safe_host("") is False


def test_abort_planning():
    abort_plan = Commander.plan_abort()
    if sys.platform == "win32":
        assert abort_plan["supported"] is True
        assert "shutdown.exe" in abort_plan["display"]
        assert "/a" in abort_plan["display"]
    else:
        assert abort_plan["supported"] is False


def test_unknown_action_raises():
    try:
        Commander.plan("explode", 0, False)
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_execute_reports_failure():
    """Executing a nonexistent program must report ok=False with an error."""
    plan = {"program": "definitely-not-a-real-program-xyz", "args": [], "display": "x"}
    ok, display, pid, err = Commander.execute(plan)
    assert ok is False
    assert err


def test_execute_missing_program():
    ok, display, pid, err = Commander.execute({"program": "", "args": []})
    assert ok is False
    assert err == "No program specified"


def test_execute_success_exit_code():
    """A command that exits non-zero must report ok=False (exit-code checking)."""
    import sys as _sys

    if _sys.platform == "win32":
        plan = {"program": "cmd.exe", "args": ["/c", "exit 3"], "display": "cmd exit 3"}
    else:
        plan = {"program": "sh", "args": ["-c", "exit 3"], "display": "sh exit 3"}
    ok, display, pid, err = Commander.execute(plan)
    assert ok is False
    assert err


def test_delay_validation():
    try:
        Commander.plan("shutdown", delay_secs="abc")
        raise AssertionError("should have raised for non-integer delay")
    except ValueError:
        pass
