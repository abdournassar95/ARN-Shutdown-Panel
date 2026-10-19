"""Password hashing and session-revocation regression tests."""

import json

import pytest

from core import settings as settings_mod
from core.remote_server import RemoteServer
from core.security import hash_password, is_password_hash, verify_password


def test_hash_and_verify_roundtrip():
    stored = hash_password("s3cret-password")
    assert is_password_hash(stored)
    assert stored.count("$") == 3
    assert verify_password("s3cret-password", stored) is True
    assert verify_password("wrong", stored) is False
    assert "s3cret-password" not in stored


def test_verify_rejects_garbage_and_plaintext():
    assert verify_password("admin", "admin") is False
    assert verify_password("", hash_password("x")) is False
    assert verify_password("x", "") is False
    assert verify_password("x", "pbkdf2_sha256$bad") is False


def test_settings_migrates_plaintext_password(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"remotePassword": "legacy-pass"}), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "get_settings_path", lambda: path)

    mgr = settings_mod.SettingsManager()
    assert "remotePassword" not in mgr.settings
    assert is_password_hash(mgr.settings["remotePasswordHash"])
    assert mgr.verify_remote_password("legacy-pass") is True
    assert mgr.verify_remote_password("admin") is False

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "remotePassword" not in saved
    assert is_password_hash(saved["remotePasswordHash"])


def test_rotate_token_invalidates_previous_sessions():
    srv = RemoteServer(on_command=lambda a, d, f: {"ok": True}, on_abort=lambda: {"ok": True})
    old_master = srv.token
    session = srv.create_session()

    new_token = srv.rotate_token()

    assert new_token != old_master
    assert srv.is_valid_token(old_master) is False
    assert srv.is_valid_token(session) is False
    assert srv.is_valid_token(new_token) is True
    assert list(srv.sessions) == [new_token]


def test_set_credentials_revokes_sessions_and_updates_hash():
    srv = RemoteServer(
        on_command=lambda a, d, f: {"ok": True},
        on_abort=lambda: {"ok": True},
        username="admin",
        password="admin",
    )
    session = srv.create_session()
    assert srv.verify_credentials("admin", "admin") is True

    srv.set_credentials("owner", "new-strong-pass")

    assert srv.verify_credentials("admin", "admin") is False
    assert srv.verify_credentials("owner", "new-strong-pass") is True
    assert srv.is_valid_token(session) is False


@pytest.mark.parametrize("bad", ["", " ", "admin"])
def test_empty_or_default_password_never_verifies(bad):
    srv = RemoteServer(
        on_command=lambda a, d, f: {"ok": True},
        on_abort=lambda: {"ok": True},
        password_hash=hash_password("real-password"),
    )
    assert srv.verify_credentials("admin", bad) is False
