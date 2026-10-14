import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile


from core.input_controller import InputController
from core.remote_server import RemoteServer, get_local_ips, get_system_drives
from core.screen_streamer import ScreenStreamer


def test_input_controller_screen_size():
    size = InputController.get_screen_size()
    assert "width" in size and "height" in size
    assert size["width"] > 0 and size["height"] > 0


def test_screen_streamer_capture():
    frame = ScreenStreamer.capture_frame(scale=0.2, quality=30)
    assert isinstance(frame, bytes)
    assert len(frame) > 100
    # Check JPEG header
    assert frame.startswith(b"\xff\xd8")


def test_screen_streamer_generator():
    gen = ScreenStreamer.generate_mjpeg_frames(
        fps=10, scale=0.1, quality=20, max_duration_secs=1
    )
    chunk = next(gen)
    assert b"--frame" in chunk
    assert b"Content-Type: image/jpeg" in chunk


def test_remote_server_qr_code():
    server = RemoteServer(
        on_command=lambda a, d, f: {"ok": True}, on_abort=lambda: {"ok": True}
    )
    qr_uri = server.get_qr_data_uri()
    assert qr_uri.startswith("data:image/png;base64,")


def test_system_drives_and_ips():
    drives = get_system_drives()
    assert len(drives) > 0
    ips = get_local_ips()
    assert "127.0.0.1" in ips


def test_remote_server_http_endpoints():
    executed_commands = []

    def mock_cmd(action, delay, force):
        executed_commands.append((action, delay, force))
        return {"ok": True, "display": f"{action} executed"}

    def mock_abort():
        return {"ok": True, "display": "aborted"}

    server = RemoteServer(on_command=mock_cmd, on_abort=mock_abort)
    # Start on loopback with free port
    port = 18088
    status = server.start(bind="127.0.0.1", port=port)
    assert status["running"] is True
    time.sleep(0.2)

    base_url = f"http://127.0.0.1:{port}"
    token = server.token

    try:
        # 1. Test Web UI (GET /)
        req = urllib.request.Request(f"{base_url}/")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "Shutdown Panel" in html
            assert "trackpadArea" in html

        # 2. Test QR Code endpoint (GET /api/qr with auth)
        req = urllib.request.Request(
            f"{base_url}/api/qr", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "image/png"

        # 3. Test Unauthorized Access (GET /api/fs/list)
        req = urllib.request.Request(f"{base_url}/api/fs/list")
        try:
            urllib.request.urlopen(req)
            assert False, "Should have thrown 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401

        # 4. Test Authorized fs/list drives
        req = urllib.request.Request(
            f"{base_url}/api/fs/list", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert len(data["drives"]) > 0

        # 5. Test Authorized fs/list current workspace dir
        workspace_dir = os.path.abspath(".")
        req = urllib.request.Request(
            f"{base_url}/api/fs/list?path=" + urllib.parse.quote(workspace_dir),
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            names = [item["name"] for item in data["items"]]
            assert "main.py" in names

        # 6. Test Download Folder as ZIP
        req = urllib.request.Request(
            f"{base_url}/api/fs/download_zip?path="
            + urllib.parse.quote(os.path.join(workspace_dir, "core")),
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "application/zip"
            zip_data = resp.read()
            zf = zipfile.ZipFile(io.BytesIO(zip_data))
            assert "remote_server.py" in zf.namelist()

        # 7. Test Media Control API (POST /api/media/control)
        payload = json.dumps({"action": "play_pause"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/media/control",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True

        # 8. Test Command API (POST /api/command)
        payload = json.dumps({"action": "lock", "delaySecs": 0}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/command",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert ("lock", 0, False) in executed_commands

    finally:
        server.stop()
