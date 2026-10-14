"""
Tests for Custom Remote Lock Screen feature.
Verifies AppAPI locking/unlocking, password validation,
and RemoteServer lock API endpoints (/api/lock/status, /api/lock/activate, /api/lock/unlock).
"""

import json
import time
import urllib.error
import urllib.request
import pytest

from core.remote_server import RemoteServer
from gui.api import AppAPI


class MockWindow:
    def __init__(self):
        self.shown = False
        self.hidden = False
        self.js_calls = []

    def show(self):
        self.shown = True
        self.hidden = False

    def hide(self):
        self.hidden = True
        self.shown = False

    def evaluate_js(self, script: str):
        self.js_calls.append(script)


@pytest.fixture
def app_api(tmp_path, monkeypatch):
    """Creates an isolated AppAPI instance with settings in tmp_path."""
    from core import settings as settings_mod

    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({
        "remotePassword": "secret_password",
        "remoteToken": "TEST_TOKEN_12345",
        "remoteEnabled": False,
    }), encoding="utf-8")

    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: settings_file)

    api = AppAPI()
    mock_lock_win = MockWindow()
    api.set_lock_window(mock_lock_win)
    yield api
    api.schedule_engine.stop()


def test_api_lock_screen_default_message(app_api):
    res = app_api.lock_screen()
    assert res["ok"] is True
    assert res["locked"] is True
    assert app_api.is_screen_locked() is True
    assert "الجهاز تحت الصيانة" in res["message"]
    assert app_api._lock_window.shown is True
    assert len(app_api._lock_window.js_calls) > 0


def test_api_lock_screen_custom_message(app_api):
    custom_msg = "يرجى عدم لمس الحاسوب - جاري فحص ملفات العمل"
    res = app_api.lock_screen(custom_msg)
    assert res["ok"] is True
    assert res["message"] == custom_msg
    status = app_api.get_lock_status()
    assert status["locked"] is True
    assert status["message"] == custom_msg


def test_api_unlock_with_incorrect_password(app_api):
    app_api.lock_screen("قيد الصيانة")
    res = app_api.unlock_screen("wrong_pwd")
    assert res["ok"] is False
    assert "كلمة المرور غير صحيحة" in res["error"]
    assert app_api.is_screen_locked() is True


def test_api_unlock_with_correct_password(app_api):
    app_api.lock_screen("قيد الصيانة")
    res = app_api.unlock_screen("secret_password")
    assert res["ok"] is True
    assert res["locked"] is False
    assert app_api.is_screen_locked() is False
    assert app_api._lock_window.hidden is True


def test_api_remote_unlock(app_api):
    app_api.lock_screen("قفل عن بعد")
    assert app_api.is_screen_locked() is True
    res = app_api.remote_unlock_screen()
    assert res["ok"] is True
    assert res["locked"] is False
    assert app_api.is_screen_locked() is False


def test_remote_server_lock_endpoints():
    lock_state = {"locked": False, "message": ""}

    def on_lock(msg):
        lock_state["locked"] = True
        lock_state["message"] = msg
        return {"ok": True, "locked": True, "message": msg}

    def on_unlock():
        lock_state["locked"] = False
        lock_state["message"] = ""
        return {"ok": True, "locked": False}

    def lock_status():
        return {"ok": True, "locked": lock_state["locked"], "message": lock_state["message"]}

    server = RemoteServer(
        on_command=lambda a, d, f: {"ok": True},
        on_abort=lambda: {"ok": True},
        token="MYTOKEN",
        on_lock=on_lock,
        on_unlock=on_unlock,
        lock_status_provider=lock_status,
    )
    server.start(bind="127.0.0.1", port=0)
    time.sleep(0.1)

    try:
        base_url = f"http://127.0.0.1:{server.port}"

        # 1. GET /api/lock/status (initial)
        req = urllib.request.Request(
            f"{base_url}/api/lock/status",
            headers={"Authorization": "Bearer MYTOKEN"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["ok"] is True
            assert data["locked"] is False

        # 2. POST /api/lock/activate
        payload = json.dumps({"message": "الجهاز قيد التحديث"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/lock/activate",
            data=payload,
            headers={"Authorization": "Bearer MYTOKEN", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["ok"] is True
            assert data["locked"] is True
            assert data["message"] == "الجهاز قيد التحديث"
            assert lock_state["locked"] is True

        # 3. GET /api/lock/status (after locking)
        req = urllib.request.Request(
            f"{base_url}/api/lock/status",
            headers={"Authorization": "Bearer MYTOKEN"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["locked"] is True
            assert data["message"] == "الجهاز قيد التحديث"

        # 4. POST /api/lock/unlock
        req = urllib.request.Request(
            f"{base_url}/api/lock/unlock",
            data=b"{}",
            headers={"Authorization": "Bearer MYTOKEN", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["ok"] is True
            assert data["locked"] is False
            assert lock_state["locked"] is False

        # 5. POST /api/command with action: custom_lock
        payload = json.dumps({"action": "custom_lock", "message": "أمر مخصص"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/command",
            data=payload,
            headers={"Authorization": "Bearer MYTOKEN", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["ok"] is True
            assert lock_state["locked"] is True
            assert lock_state["message"] == "أمر مخصص"

    finally:
        server.stop()
