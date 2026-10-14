import json

from core.settings import DEFAULT_SETTINGS, SettingsManager


def test_defaults_and_merge(tmp_path, monkeypatch):
    from core import settings as settings_mod

    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: path)

    mgr = SettingsManager()
    assert mgr.settings["language"] == "ar"
    assert mgr.settings["remoteToken"] == ""
    assert mgr.settings["startMinimized"] is True
    assert mgr.settings["widgetStyle"] == "cyber"
    assert mgr.settings["countdownStyle"] == "hud"
    assert "schedules" in mgr.settings


def test_save_load_roundtrip(tmp_path, monkeypatch):
    from core import settings as settings_mod

    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: path)

    mgr = SettingsManager()
    saved = mgr.save({"language": "en", "remotePort": 9090})
    assert saved["language"] == "en"
    assert saved["remotePort"] == 9090

    # A fresh manager must read back the same values
    mgr2 = SettingsManager()
    assert mgr2.settings["language"] == "en"
    assert mgr2.settings["remotePort"] == 9090
    # defaults still apply for untouched keys
    assert mgr2.settings["theme"] == DEFAULT_SETTINGS["theme"]


def test_atomic_write_no_tmp_leftover(tmp_path, monkeypatch):
    from core import settings as settings_mod

    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: path)

    mgr = SettingsManager()
    mgr.save({"theme": "light"})
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["theme"] == "light"


def test_corrupt_file_falls_back_to_defaults(tmp_path, monkeypatch):
    from core import settings as settings_mod

    path = tmp_path / "settings.json"
    path.write_text("{ not valid json !!", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: path)

    mgr = SettingsManager()
    assert mgr.settings == DEFAULT_SETTINGS.copy()
