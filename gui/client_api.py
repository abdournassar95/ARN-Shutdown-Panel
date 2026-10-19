"""
Shutdown Panel — Desktop Client API Bridge.
Proxies all JS calls through Python's urllib to the remote server,
bypassing CORS restrictions. Also handles UDP auto-discovery.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from core.app_logger import get_logger
from core.discovery import UDPListener


class ClientAPI:
    """pywebview JS-API for the desktop client application."""

    def __init__(self):
        self._window = None
        self.logger = get_logger()
        self._server_url: Optional[str] = None
        self._token: Optional[str] = None
        self._session_token: Optional[str] = None
        self._discovered: Dict[str, Dict[str, Any]] = {}
        self._listener: Optional[UDPListener] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------
    def set_window(self, window):
        self._window = window

    def minimize_window(self):
        if self._window:
            self._window.minimize()

    def toggle_fullscreen(self):
        if self._window:
            self._window.toggle_fullscreen()

    def close_window(self):
        if self._window:
            import os
            os._exit(0)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def start_discovery(self):
        """Start listening for server UDP beacons."""
        if self._listener:
            return
        self._listener = UDPListener(on_discovered=self._on_server_found)
        self._listener.start()
        self.logger.info("UDP discovery listener started")

    def stop_discovery(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_server_found(self, msg: Dict[str, Any]):
        key = f"{msg.get('ip')}:{msg.get('port')}"
        with self._lock:
            self._discovered[key] = {
                "ip": msg.get("ip"),
                "port": msg.get("port"),
                "name": msg.get("name", "Unknown"),
                "lastSeen": time.time(),
            }

    def get_discovered_servers(self) -> list:
        """Returns list of discovered servers (called from JS)."""
        now = time.time()
        with self._lock:
            # Remove stale entries (not seen in 10 seconds)
            self._discovered = {
                k: v for k, v in self._discovered.items()
                if now - v.get("lastSeen", 0) < 10
            }
            return list(self._discovered.values())

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self, ip: str, port: int, token: str = "") -> dict:
        """Connects to a server.

        With a token, the token is verified; without one, reachability is
        probed and the caller is told that authentication is required.
        """
        if token and token.strip():
            return self.connect_with_token(ip, port, token)

        self._server_url = f"http://{ip}:{port}"
        self._token = ""
        self._session_token = None

        self.logger.info(f"API connect called for {self._server_url}")

        try:
            url = f"{self._server_url}/"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5.0):
                return {"ok": True, "needsAuth": True}
        except urllib.error.HTTPError as e:
            # 401/403 means a Shutdown Panel server answered (but wants auth).
            if e.code in (401, 403):
                return {"ok": True, "needsAuth": True}
            self.logger.warning(f"API connect: unexpected HTTP {e.code}")
            self._server_url = None
            return {"ok": False, "error": f"Unexpected HTTP {e.code}"}
        except Exception as e:
            self.logger.error(f"API connect failed: {e}")
            self._server_url = None
            return {"ok": False, "error": str(e)}

    def login(self, username: str, password: str) -> dict:
        """Login with credentials to get a session token."""
        self.logger.info(f"API login called with {username} for server {self._server_url}")
        if not self._server_url:
            self.logger.warning("API login failed: Not connected")
            return {"ok": False, "error": "Not connected"}
        try:
            import base64
            creds = base64.b64encode(f"{username}:{password}".encode()).decode()
            url = f"{self._server_url}/api/auth/login"
            data_bytes = json.dumps({"username": username, "password": password}).encode("utf-8")
            self.logger.info(f"Sending POST to {url}")
            req = urllib.request.Request(url, data=data_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Basic {creds}")
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result and result.get("ok"):
                    self._session_token = result.get("token", "")
                    self._token = self._session_token
                    return {"ok": True, "token": self._session_token}
                return {"ok": False, "error": result.get("error", "Login failed")}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err_data = json.loads(body)
                return {"ok": False, "error": err_data.get("error", f"HTTP {e.code}")}
            except Exception:
                return {"ok": False, "error": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def connect_with_token(self, ip: str, port: int, token: str) -> dict:
        """Connect using a token directly."""
        self.logger.info(f"API connect_with_token called for {ip}:{port}")
        if not token or not token.strip():
            # No token provided — just test reachability
            return self.connect(ip, port)
        
        self._server_url = f"http://{ip}:{port}"
        self._token = token.strip().upper()
        self._session_token = token.strip().upper()
        try:
            data = self._api_get("/api/system/summary")
            if data and data.get("ok"):
                return {"ok": True}
            return {"ok": False, "needsAuth": True, "error": "Invalid token"}
        except Exception as e:
            # Token invalid but server reachable? Check via root
            try:
                url = f"{self._server_url}/"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5.0):
                    self._token = ""
                    self._session_token = None
                    return {"ok": True, "needsAuth": True}
            except urllib.error.HTTPError:
                self._token = ""
                self._session_token = None
                return {"ok": True, "needsAuth": True}
            except Exception:
                pass
            self._server_url = None
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self._server_url = None
        self._token = None
        self._session_token = None
        return {"ok": True}

    def is_connected(self) -> bool:
        return self._server_url is not None and self._session_token is not None

    # ------------------------------------------------------------------
    # Proxy API calls
    # ------------------------------------------------------------------
    def api_get(self, path: str) -> dict:
        """Generic GET proxy (called from JS)."""
        try:
            return self._api_get(path) or {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def api_post(self, path: str, body_json: str) -> dict:
        """Generic POST proxy (called from JS)."""
        try:
            body = json.loads(body_json) if isinstance(body_json, str) else body_json
            return self._api_post(path, body) or {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Lock screen controls
    # ------------------------------------------------------------------
    def get_lock_status(self) -> dict:
        """Retrieve host PC lock screen status (/api/lock/status)."""
        try:
            return self._api_get("/api/lock/status") or {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def activate_lock(self, message: str = "") -> dict:
        """Activate the remote custom lock screen on the host PC (POST /api/lock/activate)."""
        try:
            msg = str(message).strip() if message is not None else ""
            if not msg:
                msg = "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
            return self._api_post("/api/lock/activate", {"message": msg}) or {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def unlock_lock(self) -> dict:
        """Remotely unlock the host PC's custom lock screen (POST /api/lock/unlock)."""
        try:
            return self._api_post("/api/lock/unlock", {}) or {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_stream_url(self, path: str = "/api/screen/stream") -> str:
        """Returns the full URL for the MJPEG stream (img.src needs a direct URL)."""
        if not self._server_url or not self._session_token:
            return ""
        token = self._session_token or self._token or ""
        return f"{self._server_url}{path}?fps=30&scale=0.8&q=65&token={token}"

    def get_frame_url(self, quality: int = 95) -> str:
        """Returns a snapshot URL."""
        if not self._server_url:
            return ""
        token = self._session_token or self._token or ""
        return f"{self._server_url}/api/screen/frame?q={quality}&token={token}"

    def get_download_url(self, file_path: str) -> str:
        """Returns the direct download URL for a file."""
        if not self._server_url:
            return ""
        token = self._session_token or self._token or ""
        encoded = urllib.parse.quote(file_path, safe="")
        return f"{self._server_url}/api/fs/download?path={encoded}&token={token}"

    def get_server_url(self) -> str:
        return self._server_url or ""

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------
    def _get_auth_token(self) -> str:
        return self._session_token or self._token or ""

    def _api_get(self, path: str, timeout: float = 8.0) -> dict:
        if not self._server_url:
            raise ConnectionError("Not connected to any server")
        
        url = f"{self._server_url}{path}"
        sep = "&" if "?" in url else "?"
        url += f"{sep}token={urllib.parse.quote(self._get_auth_token())}"
        
        req = urllib.request.Request(url, method="GET")
        req.add_header("X-Auth-Token", self._get_auth_token())
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _api_post(self, path: str, body: dict = None, timeout: float = 8.0,
                  use_basic_auth: tuple = None) -> dict:
        if not self._server_url:
            raise ConnectionError("Not connected to any server")
        
        url = f"{self._server_url}{path}"
        data = json.dumps(body or {}).encode("utf-8")
        
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Auth-Token", self._get_auth_token())
        
        if use_basic_auth:
            import base64
            creds = base64.b64encode(f"{use_basic_auth[0]}:{use_basic_auth[1]}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
