import unittest.mock as mock
from gui.api import AppAPI


def test_api_open_url_success(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    api = AppAPI()
    try:
        with mock.patch("webbrowser.open", return_value=True) as mock_open:
            res = api.open_url("https://wa.me/201556710314")
            assert res is True
            mock_open.assert_called_once_with("https://wa.me/201556710314")
    finally:
        api.remote_server.stop()
        api.scheduler.cancel()
        api.schedule_engine.stop()


def test_api_open_url_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    api = AppAPI()
    try:
        with mock.patch("webbrowser.open", side_effect=Exception("Browser launch failed")):
            res = api.open_url("https://wa.me/201556710314")
            assert res is False
    finally:
        api.remote_server.stop()
        api.scheduler.cancel()
        api.schedule_engine.stop()

