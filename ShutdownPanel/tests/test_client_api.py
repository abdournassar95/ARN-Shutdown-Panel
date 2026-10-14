import time
from gui.client_api import ClientAPI
from core.remote_server import RemoteServer


def test_client_api_discovery_tracking():
    api = ClientAPI()
    assert api.get_discovered_servers() == []

    # Simulate discovery message
    api._on_server_found({
        "ip": "192.168.1.50",
        "port": 8080,
        "name": "Office-PC"
    })

    servers = api.get_discovered_servers()
    assert len(servers) == 1
    assert servers[0]["name"] == "Office-PC"
    assert servers[0]["ip"] == "192.168.1.50"
    assert servers[0]["port"] == 8080

    # Simulate stale server (>10s old)
    api._discovered["192.168.1.50:8080"]["lastSeen"] = time.time() - 15
    assert api.get_discovered_servers() == []


def test_client_api_urls():
    api = ClientAPI()
    # Before connection
    assert api.get_stream_url() == ""
    assert api.get_frame_url() == ""
    assert api.get_download_url("test.txt") == ""
    assert api.is_connected() is False

    # Simulate connected state
    api._server_url = "http://127.0.0.1:8080"
    api._session_token = "ABC123XYZ"
    assert api.is_connected() is True
    assert "token=ABC123XYZ" in api.get_stream_url()
    assert "token=ABC123XYZ" in api.get_frame_url()
    assert "test%20file.txt" in api.get_download_url("test file.txt")

    api.disconnect()
    assert api.is_connected() is False


def get_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_client_api_integration_with_remote_server():
    port = get_free_port()
    server = RemoteServer(
        on_command=lambda cmd, delay, force: {"ok": True},
        on_abort=lambda: {"ok": True},
        token="SECRET_TOKEN_123",
        username="admin",
        password="password123",
    )
    server.start("127.0.0.1", port)
    time.sleep(0.1)

    api = ClientAPI()
    try:
        # 1. Connect without token (checks reachability)
        res = api.connect("127.0.0.1", port)
        assert res["ok"] is True
        assert res.get("needsAuth") is True

        # 2. Login with credentials
        bad_login = api.login("admin", "wrong_pass")
        assert bad_login["ok"] is False

        good_login = api.login("admin", "password123")
        assert good_login["ok"] is True
        assert bool(good_login.get("token")) is True
        assert api.is_connected() is True

        # 3. Perform api_get through proxy
        summary = api.api_get("/api/system/summary")
        assert summary["ok"] is True

        # 4. Perform api_post through proxy
        cmd_res = api.api_post("/api/command", {"action": "sleep", "delaySecs": 0})
        assert cmd_res.get("ok") is True

    finally:
        server.stop()
        api.disconnect()


def test_client_api_lock_methods():
    api = ClientAPI()
    # When disconnected, should return ok: False cleanly without crashing
    assert api.get_lock_status()["ok"] is False
    assert api.activate_lock("test")["ok"] is False
    assert api.unlock_lock()["ok"] is False

    port = get_free_port()
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
        on_command=lambda cmd, delay, force: {"ok": True},
        on_abort=lambda: {"ok": True},
        token="SECRET_TOKEN_LOCK",
        username="admin",
        password="password123",
        on_lock=on_lock,
        on_unlock=on_unlock,
        lock_status_provider=lock_status,
    )
    server.start("127.0.0.1", port)
    time.sleep(0.1)

    try:
        res = api.connect("127.0.0.1", port)
        assert res["ok"] is True
        login_res = api.login("admin", "password123")
        assert login_res["ok"] is True

        # 1. get_lock_status (initially unlocked)
        status = api.get_lock_status()
        assert status["ok"] is True
        assert status["locked"] is False

        # 2. activate_lock with custom message
        act_res = api.activate_lock("الصيانة مستمرة")
        assert act_res["ok"] is True
        assert act_res["locked"] is True
        assert act_res["message"] == "الصيانة مستمرة"
        assert lock_state["locked"] is True
        assert lock_state["message"] == "الصيانة مستمرة"

        # 3. get_lock_status verifies locked
        status_locked = api.get_lock_status()
        assert status_locked["ok"] is True
        assert status_locked["locked"] is True
        assert status_locked["message"] == "الصيانة مستمرة"

        # 4. unlock_lock
        unlock_res = api.unlock_lock()
        assert unlock_res["ok"] is True
        assert unlock_res["locked"] is False
        assert lock_state["locked"] is False

        # 5. get_lock_status verifies unlocked
        status_unlocked = api.get_lock_status()
        assert status_unlocked["ok"] is True
        assert status_unlocked["locked"] is False

        # 6. activate_lock with empty string uses default message
        act_default = api.activate_lock("")
        assert act_default["ok"] is True
        assert act_default["locked"] is True
        assert "الجهاز تحت الصيانة" in act_default["message"]

    finally:
        server.stop()
        api.disconnect()
