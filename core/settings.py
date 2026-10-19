"""
Settings persistence module (v2).
Saves user preferences to a JSON file (atomic writes) in AppData
or the user profile directory.
"""

import json
import os
import pathlib
from typing import Any, Dict

from core.security import hash_password
from core.version import __version__

DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": __version__,
    "language": "ar",
    "theme": "dark",
    "sounds": True,
    "askConfirm": False,
    "force": False,
    "showStats": True,
    "autoStart": False,
    "warnBefore": 30,
    "remoteEnabled": False,
    "remotePort": 8080,
    "remoteBind": "0.0.0.0",
    "remoteUsername": "admin",
    # Hashed with PBKDF2 (see core/security.py). The legacy plain-text key
    # "remotePassword" is migrated on load and never written again.
    "remotePasswordHash": "",
    "remoteToken": "",
    "httpsEnabled": False,
    "startMinimized": True,
    "widgetStyle": "cyber",
    "countdownStyle": "hud",
    "schedules": [],
}


def get_settings_path() -> pathlib.Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        base_dir = pathlib.Path(appdata) / "ShutdownPanelPython"
    else:
        base_dir = pathlib.Path.home() / ".shutdown_panel_python"
    return base_dir / "settings.json"


class SettingsManager:
    def __init__(self):
        self.path = get_settings_path()
        self.settings: Dict[str, Any] = self.load()
        self._migrate_plaintext_password()

    def _migrate_plaintext_password(self):
        """Hashes a legacy plain-text password and removes it from disk."""
        legacy = self.settings.pop("remotePassword", None)
        if legacy and not self.settings.get("remotePasswordHash"):
            self.settings["remotePasswordHash"] = hash_password(str(legacy))
            self.save({})
        elif legacy is not None:
            # Plain-text key present but a hash already exists: drop it.
            self.save({})

    def verify_remote_password(self, password: str) -> bool:
        """Checks *password* against the stored hash."""
        from core.security import verify_password

        return verify_password(password, self.settings.get("remotePasswordHash", ""))

    def set_remote_password(self, password: str, persist: bool = True) -> str:
        """Hashes and stores a new LAN password; returns the hash."""
        new_hash = hash_password(password)
        if persist:
            self.save({"remotePasswordHash": new_hash})
        else:
            self.settings["remotePasswordHash"] = new_hash
        return new_hash

    def load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    res = DEFAULT_SETTINGS.copy()
                    res.update(data)
                    return res
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    def save(self, next_settings: Dict[str, Any]) -> Dict[str, Any]:
        merged = (self.settings.copy() if hasattr(self, "settings") and self.settings else DEFAULT_SETTINGS.copy())
        merged.update(next_settings)
        # Never persist stale version info or a plain-text password
        merged["version"] = __version__
        merged.pop("remotePassword", None)
        self.settings = merged
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)  # atomic on same filesystem
            try:
                # Best effort: keep the credential file private to the user.
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception as e:
            from core.app_logger import get_logger

            get_logger().warning("Failed to save settings: %s", e)
        return merged
