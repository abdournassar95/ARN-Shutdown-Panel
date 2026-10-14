"""
Settings persistence module (v2).
Saves user preferences to a JSON file (atomic writes) in AppData
or the user profile directory.
"""

import json
import os
import pathlib
from typing import Any, Dict

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
    "remotePassword": "admin",
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
        # Never persist stale version info
        merged["version"] = __version__
        self.settings = merged
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)  # atomic on same filesystem
        except Exception as e:
            from core.app_logger import get_logger

            get_logger().warning("Failed to save settings: %s", e)
        return merged
