"""Comprehensive remote server tests: security, uploads, safe delete, validation."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

from core import wol as wol_mod
from core.input_controller import InputController
from core.remote_server import (
    RemoteServer,
    generate_app_icon,
    get_local_ips,
    get_system_drives,
    is_protected_path,
    sanitize_filename,
)
from core.screen_streamer import ScreenStreamer

PORT = 18123


@pytest.fixture()
def server():
    srv = RemoteServer(on_command=lambda a, d, f: {"ok": True, "display": a},
                       on_abort=lambda: {"ok": True, "display": "aborted"})
    srv.start(bind="127.0.0.1", port=PORT)
    time.sleep(0.2)
    yield srv
    srv.stop()
    time.sleep(0.05)


def _req(path, method="GET", payload=None, token=None, headers=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# ---------------------------------------------------------------- public
def test_mobile_page_served(server):
    status, body, headers = _req("/")
    assert status == 200
    html = body.decode("utf-8")
    assert "Shutdown Panel" in html
    assert "trackpadArea" in html


def test_public_status_has_no_token(server):
    """The public /api/status must never leak the access token."""
    status, body, _ = _req("/api/status")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert "token" not in data


def test_pwa_assets(server):
    status, body, headers = _req("/manifest.webmanifest")
    assert status == 200
    assert "manifest" in headers.get("Content-Type", "")
    status, body, headers = _req("/icon.png")
    assert status == 200
    assert body.startswith(b"\x89PNG")


# ---------------------------------------------------------------- security
def test_qr_endpoint_requires_auth(server):
    """SECURITY REGRESSION: /api/qr embeds the token and must be authenticated."""
    status, body, _ = _req("/api/qr")
    assert status == 401, "QR endpoint must not be public (it contains the token!)"


def test_qr_with_auth(server):
    status, body, headers = _req("/api/qr", token=server.token)
    assert status == 200
    assert headers.get("Content-Type") == "image/png"
    assert body.startswith(b"\x89PNG")


def test_no_cors_wildcard(server):
    """CORS must NOT be open to all origins (same-origin app)."""
    status, body, headers = _req("/")
    assert "Access-Control-Allow-Origin" not in headers


def test_unauthorized_requests_rejected(server):
    for path in ("/api/fs/list", "/api/system/summary", "/api/clipboard"):
        status, body, _ = _req(path)
        assert status == 401, path
    status, body, _ = _req("/api/command", method="POST", payload={"action": "shutdown"})
    assert status == 401


def test_wrong_token_rejected(server):
    status, body, _ = _req("/api/fs/list", token="WRONGTOKEN123")
    assert status == 401


# ---------------------------------------------------------------- validation
def test_invalid_payload_returns_400_not_crash(server):
    status, body, _ = _req(
        "/api/command", method="POST", payload={"action": "shutdown", "delaySecs": "abc"},
        token=server.token,
    )
    assert status == 400
    data = json.loads(body)
    assert data["ok"] is False
    assert "error" in data


def test_invalid_stream_params_rejected(server):
    for q in ("fps=999", "scale=50", "q=200"):
        status, body, _ = _req(f"/api/screen/stream?{q}", token=server.token)
        assert status == 400, q


def test_malformed_json_returns_400(server):
    url = f"http://127.0.0.1:{PORT}/api/command"
    req = urllib.request.Request(
        url, data=b"{invalid json", method="POST",
        headers={"Authorization": f"Bearer {server.token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        e.read()
    assert status == 400


# ---------------------------------------------------------------- fs list
def test_fs_list_drives_and_breadcrumbs(server):
    status, body, _ = _req("/api/fs/list", token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert len(data["drives"]) > 0

    # List a real directory with breadcrumbs
    target = tempfile.mkdtemp(prefix="sp_test_")
    with open(os.path.join(target, "hello.txt"), "w") as f:
        f.write("x")
    status, body, _ = _req(
        "/api/fs/list?path=" + urllib.parse.quote(target), token=server.token
    )
    data = json.loads(body)
    assert data["ok"] is True
    assert "hello.txt" in [i["name"] for i in data["items"]]
    # POSIX breadcrumbs must be absolute paths
    if sys.platform != "win32":
        assert all(c["path"].startswith("/") for c in data["breadcrumbs"])


# ---------------------------------------------------------------- uploads
def _multipart_body(target_dir, filename, content, boundary=b"SPBOUNDARY42"):
    return (
        f"--{boundary.decode()}\r\n"
        f'Content-Disposition: form-data; name="target_path"\r\n\r\n'
        f"{target_dir}\r\n"
        f"--{boundary.decode()}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary.decode()}--\r\n".encode("utf-8")


def _upload(server, target_dir, filename, content, boundary=b"SPBOUNDARY42"):
    body = _multipart_body(target_dir, filename, content, boundary)
    url = f"http://127.0.0.1:{PORT}/api/fs/upload"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {server.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_upload_file_streaming(server):
    """The cgi-replacement multipart parser must write exact file bytes."""
    target = tempfile.mkdtemp(prefix="sp_upload_")
    content = os.urandom(300_000)  # larger than one read chunk
    status, data = _upload(server, target, "data.bin", content)
    assert status == 200
    assert data["ok"] is True
    with open(os.path.join(target, "data.bin"), "rb") as f:
        assert f.read() == content


def test_upload_arabic_filename(server):
    target = tempfile.mkdtemp(prefix="sp_upload_")
    status, data = _upload(server, target, "تقرير الملف.txt", "مرحبا".encode("utf-8"))
    assert status == 200
    assert os.path.isfile(os.path.join(target, "تقرير الملف.txt"))


def test_upload_filename_traversal_blocked(server):
    target = tempfile.mkdtemp(prefix="sp_upload_")
    status, data = _upload(server, target, "..\\..\\evil.txt", b"x")
    assert status == 200
    assert not os.path.exists(os.path.join(target, "..", "..", "evil.txt"))
    assert os.path.isfile(os.path.join(target, "evil.txt"))


def test_upload_size_limit(server):
    small = RemoteServer(on_command=lambda a, d, f: {"ok": True},
                         on_abort=lambda: {"ok": True}, max_upload=2048)
    small.start(bind="127.0.0.1", port=PORT + 1)
    time.sleep(0.2)
    try:
        target = tempfile.mkdtemp(prefix="sp_limit_")
        url = f"http://127.0.0.1:{PORT + 1}/api/fs/upload"
        body = _multipart_body(target, "big.bin", os.urandom(64_000))
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": f"Bearer {small.token}",
                     "Content-Type": "multipart/form-data; boundary=SPBOUNDARY42"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 413
    finally:
        small.stop()


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("") == "upload.bin"
    assert sanitize_filename('a<b>:c|"d') == "a_b__c__d"


# ---------------------------------------------------------------- safe delete
def test_delete_moves_to_trash(server):
    target = tempfile.mkdtemp(prefix="sp_del_")
    fp = os.path.join(target, "todelete.txt")
    with open(fp, "w") as f:
        f.write("bye")
    status, body, _ = _req("/api/fs/delete", method="POST", payload={"path": fp},
                        token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert not os.path.exists(fp), "file must be gone from its original location"


def test_delete_protected_paths_rejected(server):
    protected = ["/", "C:\\", os.path.expanduser("~")]
    for p in protected:
        status, body, _ = _req("/api/fs/delete", method="POST", payload={"path": p},
                            token=server.token)
        assert status == 403, p


def test_is_protected_path_unit():
    assert is_protected_path("/") is True
    assert is_protected_path("C:\\") is True
    assert is_protected_path(os.path.expanduser("~")) is True
    assert is_protected_path(os.path.join(tempfile.gettempdir(), "x")) is False


# ---------------------------------------------------------------- fs misc
def test_create_dir_and_rename(server):
    parent = tempfile.mkdtemp(prefix="sp_mk_")
    status, body, _ = _req("/api/fs/create_dir", method="POST",
                        payload={"parent_path": parent, "name": "newdir"},
                        token=server.token)
    assert status == 200
    assert os.path.isdir(os.path.join(parent, "newdir"))

    fp = os.path.join(parent, "newdir", "a.txt")
    with open(fp, "w") as f:
        f.write("1")
    status, body, _ = _req("/api/fs/rename", method="POST",
                        payload={"path": fp, "newName": "b.txt"},
                        token=server.token)
    assert status == 200
    assert os.path.isfile(os.path.join(parent, "newdir", "b.txt"))


def test_download_zip_streams_from_temp(server):
    folder = tempfile.mkdtemp(prefix="sp_src_zip_")
    with open(os.path.join(folder, "f1.txt"), "w") as f:
        f.write("hello zip")
    tmpdir = tempfile.gettempdir()
    before = {f for f in os.listdir(tmpdir) if f.startswith("sp_zip_") and f.endswith(".zip")}
    status, body, headers = _req(
        "/api/fs/download_zip?path=" + urllib.parse.quote(folder), token=server.token
    )
    assert status == 200
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert "f1.txt" in zf.namelist()
    # no NEW temp zip files left behind (wait briefly for background server thread to finish unlinking)
    after = before
    for _ in range(20):
        after = {f for f in os.listdir(tmpdir) if f.startswith("sp_zip_") and f.endswith(".zip")}
        if after == before:
            break
        time.sleep(0.05)
    assert after == before


def test_download_file(server):
    folder = tempfile.mkdtemp(prefix="sp_dl_")
    fp = os.path.join(folder, "file.txt")
    with open(fp, "w") as f:
        f.write("download me")
    status, body, headers = _req(
        "/api/fs/download?path=" + urllib.parse.quote(fp), token=server.token
    )
    assert status == 200
    assert body == b"download me"


# ---------------------------------------------------------------- processes
def test_process_list_and_kill(server):
    status, body, _ = _req("/api/proc/list", method="POST", payload={}, token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["total"] > 0

    # Spawn a disposable process and kill it through the API
    proc = subprocess.Popen(
        ["sleep", "60"] if sys.platform != "win32" else ["ping", "-n", "60", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    status, body, _ = _req("/api/proc/kill", method="POST", payload={"pid": proc.pid},
                        token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True
    proc.wait(timeout=5)


# ---------------------------------------------------------------- WoL
def test_wol_invalid_mac_rejected(server):
    status, body, _ = _req("/api/wol", method="POST", payload={"mac": "zz:zz"},
                        token=server.token)
    assert status == 400


def test_wol_endpoint_calls_wake(server, monkeypatch):
    calls = []
    monkeypatch.setattr(wol_mod, "wake", lambda mac, b="255.255.255.255", p=9, a=3:
                        calls.append(mac) or True)
    status, body, _ = _req("/api/wol", method="POST",
                        payload={"mac": "AA:BB:CC:DD:EE:FF"}, token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert calls == ["AA:BB:CC:DD:EE:FF"]


# ---------------------------------------------------------------- clipboard
def test_clipboard_endpoint_graceful(server):
    status, body, _ = _req("/api/clipboard", token=server.token)
    data = json.loads(body)
    assert "supported" in data

    status, body, _ = _req("/api/clipboard", method="POST", payload={"text": "hi"},
                        token=server.token)
    data = json.loads(body)
    assert "supported" in data


# ---------------------------------------------------------------- summary & rate limit
def test_system_summary(server):
    status, body, _ = _req("/api/system/summary", token=server.token)
    data = json.loads(body)
    assert "cpuPercent" in data
    assert "ramPercent" in data
    assert "batteryPercent" in data
    assert "host" in data


def test_rate_limit_unit():
    srv = RemoteServer(on_command=lambda a, d, f: {"ok": True},
                       on_abort=lambda: {"ok": True})
    ip = "203.0.113.77"
    assert srv.is_rate_limited(ip) is False
    for _ in range(1499):
        srv.is_rate_limited(ip)
    assert srv.is_rate_limited(ip) is True
    # localhost is never limited
    assert srv.is_rate_limited("127.0.0.1") is False


# ---------------------------------------------------------------- QR caching
def test_qr_cached_until_token_rotation(server):
    uri1 = server.get_qr_data_uri()
    uri2 = server.get_qr_data_uri()
    assert uri1 == uri2  # cached, not regenerated
    uri3 = server.get_qr_data_uri("http://192.168.1.100:8080/")
    assert uri3 != uri1


# ---------------------------------------------------------------- core extras
def test_input_controller_screen_size():
    size = InputController.get_screen_size()
    assert size["width"] > 0 and size["height"] > 0


def test_screen_streamer_capture():
    frame = ScreenStreamer.capture_frame(scale=0.2, quality=30)
    assert isinstance(frame, bytes)
    assert frame.startswith(b"\xff\xd8")


def test_screen_streamer_generator():
    gen = ScreenStreamer.generate_mjpeg_frames(fps=10, scale=0.1, quality=20,
                                               max_duration_secs=1)
    chunk = next(gen)
    assert b"--frame" in chunk
    assert b"Content-Type: image/jpeg" in chunk
    gen.close()


def test_generate_app_icon():
    data = generate_app_icon(192)
    assert data.startswith(b"\x89PNG")


def test_system_drives_and_ips():
    assert len(get_system_drives()) > 0
    assert "127.0.0.1" in get_local_ips()


# ---------------------------------------------------------------- Auth & New Endpoints
def test_auth_login_success_and_use_session(server):
    """User logs in with username & password, gets a session token, and uses it."""
    status, body, _ = _req("/api/auth/login", method="POST", payload={"username": "admin", "password": "admin"})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    session_token = data.get("token")
    assert session_token

    # Use session token to query protected endpoint
    status2, body2, _ = _req("/api/system/summary", token=session_token)
    assert status2 == 200
    data2 = json.loads(body2)
    assert data2["ok"] is True


def test_auth_login_invalid_credentials(server):
    status, body, _ = _req("/api/auth/login", method="POST", payload={"username": "admin", "password": "wrong_password"})
    assert status == 401
    data = json.loads(body)
    assert data["ok"] is False


def test_set_credentials_flow(server):
    server.set_credentials("newuser", "supersecret123")
    # Old credentials fail
    status, _, _ = _req("/api/auth/login", method="POST", payload={"username": "admin", "password": "admin"})
    assert status == 401

    # New credentials succeed
    status, body, _ = _req("/api/auth/login", method="POST", payload={"username": "newuser", "password": "supersecret123"})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True


def test_basic_auth_header(server):
    import base64
    creds = base64.b64encode(b"admin:admin").decode("ascii")
    status, body, _ = _req("/api/system/summary", headers={"Authorization": f"Basic {creds}"})
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True


def test_fs_open_endpoint(server, monkeypatch):
    # Mock os.startfile / subprocess to verify endpoint execution safely
    called = []
    if sys.platform == "win32":
        monkeypatch.setattr(os, "startfile", lambda p: called.append(p))
    else:
        monkeypatch.setattr(subprocess, "Popen", lambda cmd: called.append(cmd))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tf:
        tf.write(b"Hello PC")
        tmp_path = tf.name

    try:
        status, body, _ = _req("/api/fs/open", method="POST", payload={"path": tmp_path}, token=server.token)
        assert status == 200
        data = json.loads(body)
        assert data["ok"] is True
        assert len(called) > 0
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@pytest.mark.skipif(
    not InputController.audio_available(),
    reason="Exact volume control requires Windows Core Audio",
)
def test_media_control_volume_and_actions(server):
    # 1. Test set_volume
    status, body, _ = _req("/api/media/control", method="POST", payload={"action": "set_volume", "percent": 65}, token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["volume"] == 65

    # 2. Test get volume endpoint
    status, body, _ = _req("/api/media/volume", token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert "volume" in data

    # 3. Test volume mute & media actions
    status, body, _ = _req("/api/media/control", method="POST", payload={"action": "volume_mute"}, token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True

    status, body, _ = _req("/api/media/control", method="POST", payload={"action": "play_pause"}, token=server.token)
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True


@pytest.mark.skipif(
    not InputController.input_available(),
    reason="No input backend available (headless environment)",
)
def test_input_mouse_and_keyboard_endpoints(server):
    # Mouse move & click
    status, body, _ = _req("/api/input/mouse", method="POST", payload={"action": "move", "dx": 5, "dy": 5}, token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True

    status, body, _ = _req("/api/input/mouse", method="POST", payload={"action": "click", "button": "left"}, token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True

    # Keyboard text and hotkey
    status, body, _ = _req("/api/input/keyboard", method="POST", payload={"text": "Test"}, token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True

    status, body, _ = _req("/api/input/keyboard", method="POST", payload={"key": "enter"}, token=server.token)
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_countdown_in_summary_when_active():
    """Verify that when a countdown is active, summary includes countdown metadata."""
    srv = RemoteServer(
        on_command=lambda a, d, f: {"ok": True},
        on_abort=lambda: {"ok": True},
        metrics_provider=lambda: {
            "cpuPercent": 20,
            "ramPercent": 40,
            "countdown": {
                "action": "shutdown",
                "totalSecs": 1800,
                "remainingSecs": 1750,
                "paused": False
            }
        }
    )
    srv.start(bind="127.0.0.1", port=18129)
    time.sleep(0.2)
    try:
        url = f"http://127.0.0.1:18129/api/system/summary"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {srv.token}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert "countdown" in data
            assert data["countdown"]["action"] == "shutdown"
            assert data["countdown"]["remainingSecs"] == 1750
    finally:
        srv.stop()


# ---------------------------------------------------------------- brute-force protection
def test_login_brute_force_lockout(server):
    """After 5 failed login attempts, the IP should be locked out."""
    login_url = f"http://127.0.0.1:{PORT}/api/auth/login"
    # Send 5 failed login attempts
    for i in range(5):
        data = json.dumps({"username": "admin", "password": f"wrong{i}"}).encode("utf-8")
        req = urllib.request.Request(
            login_url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"attempt {i+1} should return 401"

    # 6th attempt should be locked out with 429
    data = json.dumps({"username": "admin", "password": "wrong5"}).encode("utf-8")
    req = urllib.request.Request(
        login_url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "Should have been locked out"
    except urllib.error.HTTPError as e:
        assert e.code == 429, f"Expected 429 lockout, got {e.code}"


# ---------------------------------------------------------------- HTTP 206 partial content
def test_download_range_partial_content(server):
    """HTTP Range header should return 206 with the correct byte slice."""
    folder = tempfile.mkdtemp(prefix="sp_range_")
    fp = os.path.join(folder, "rangetest.bin")
    content = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26 bytes
    with open(fp, "wb") as f:
        f.write(content)

    url = f"http://127.0.0.1:{PORT}/api/fs/download?path=" + urllib.parse.quote(fp)

    # Request bytes 10-19 (10 bytes: KLMNOPQRST)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {server.token}",
        "Range": "bytes=10-19",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 206
        body = resp.read()
        assert body == b"KLMNOPQRST"
        cr = resp.headers.get("Content-Range", "")
        assert cr == "bytes 10-19/26"
        assert resp.headers.get("Accept-Ranges") == "bytes"


def test_download_range_open_ended(server):
    """Range 'bytes=20-' should return bytes from offset 20 to end."""
    folder = tempfile.mkdtemp(prefix="sp_range2_")
    fp = os.path.join(folder, "rangetest2.bin")
    content = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    with open(fp, "wb") as f:
        f.write(content)

    url = f"http://127.0.0.1:{PORT}/api/fs/download?path=" + urllib.parse.quote(fp)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {server.token}",
        "Range": "bytes=20-",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 206
        body = resp.read()
        assert body == b"UVWXYZ"


def test_download_range_invalid_returns_416(server):
    """An out-of-range request should return 416."""
    folder = tempfile.mkdtemp(prefix="sp_range3_")
    fp = os.path.join(folder, "small.bin")
    with open(fp, "wb") as f:
        f.write(b"tiny")

    url = f"http://127.0.0.1:{PORT}/api/fs/download?path=" + urllib.parse.quote(fp)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {server.token}",
        "Range": "bytes=100-200",
    })
    try:
        urllib.request.urlopen(req, timeout=10)
        assert False, "Should return 416"
    except urllib.error.HTTPError as e:
        assert e.code == 416


def test_download_full_still_works(server):
    """Normal download without Range header should still return 200."""
    folder = tempfile.mkdtemp(prefix="sp_full_")
    fp = os.path.join(folder, "full.txt")
    with open(fp, "w") as f:
        f.write("full content")

    url = f"http://127.0.0.1:{PORT}/api/fs/download?path=" + urllib.parse.quote(fp)
    status, body, headers = _req(url.replace(f"http://127.0.0.1:{PORT}", ""),
                                  token=server.token)
    assert status == 200
    assert body == b"full content"
    assert headers.get("Accept-Ranges") == "bytes"
