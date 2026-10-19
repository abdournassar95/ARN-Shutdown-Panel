"""
Embedded LAN remote control server (v2).
Features: mobile web UI (served from gui/web/mobile.html), QR authentication,
full file manager (streaming uploads/downloads, safe delete), virtual
trackpad/keyboard, media/volume/brightness controls, live MJPEG screen
streaming, process manager, Wake-on-LAN, clipboard sync, and optional HTTPS.

Security model:
- Every endpoint except the mobile page, health, manifest and icon requires
  the access token (Authorization header or ?token= for media tags).
- The QR endpoint is authenticated (it embeds the token!).
- Rate limiting applies to every authenticated request.
"""

import io
import json
import mimetypes
import os
import pathlib
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil

from core.app_logger import get_logger
from core.security import hash_password, verify_password
from core.clipboard_utils import (
    clipboard_supported,
    get_clipboard_text,
    set_clipboard_text,
)
from core.input_controller import InputController
from core.screen_streamer import ScreenStreamer
from core.version import __version__
from core import wol
from core.discovery import UDPBeacon

try:
    import qrcode
except Exception:  # pragma: no cover
    qrcode = None

try:
    from send2trash import send2trash
except Exception:  # pragma: no cover
    send2trash = None

def _resolve_web_dir() -> pathlib.Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return pathlib.Path(base) / "gui" / "web"
    return pathlib.Path(__file__).resolve().parent.parent / "gui" / "web"

WEB_DIR = _resolve_web_dir()

DEFAULT_MAX_UPLOAD = 8 * 1024 * 1024 * 1024  # 8 GB
DEFAULT_MAX_ZIP = 2 * 1024 * 1024 * 1024  # 2 GB uncompressed cap
RATE_LIMIT_PER_MIN = 1500  # generous: trackpad streams many small requests
LOGIN_MAX_FAILURES = 5     # lock out after this many failed login attempts
LOGIN_LOCKOUT_SECS = 300   # 5 minutes lockout window
PROTECTED_EXACT = ["/", ""]
SYSTEM_AREA_HINTS = [
    r"^([A-Za-z]:)?\\?$",
    r"^[A-Za-z]:\\Windows(\b|\\)",
    r"^[A-Za-z]:\\Program Files(\b|\s*\(x86\)\\|\\)",
    r"^/(usr|etc|bin|sbin|boot|lib|lib64|var|opt|proc|sys|dev|root)(/|$)",
]


class ApiError(Exception):
    """HTTP-aware exception used by the request handlers."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# -----------------------------------------------------------------------------
# Small validation helpers
# -----------------------------------------------------------------------------
def as_int(value: Any, default: int, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    if value is None:
        value = default
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"Invalid integer value: {value!r}") from None
    if lo is not None and out < lo:
        raise ApiError(400, f"Value must be >= {lo}")
    if hi is not None and out > hi:
        raise ApiError(400, f"Value must be <= {hi}")
    return out


def as_float(value: Any, default: float, lo: float, hi: float) -> float:
    if value is None:
        value = default
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"Invalid numeric value: {value!r}") from None
    if not (lo <= out <= hi):
        raise ApiError(400, f"Value must be between {lo} and {hi}")
    return out


def is_protected_path(path: str) -> bool:
    """True for paths that must never be deleted/overwritten (roots, home, OS dirs)."""
    if not path:
        return True
    try:
        candidates = {path, os.path.realpath(path)}
    except Exception:
        return True
    # Windows-style variants so checks also work on POSIX hosts (tests/servers)
    variants = set()
    for c in candidates:
        variants.add(c.replace("/", "\\"))
        variants.add(c.replace("\\", "/"))
    candidates |= variants

    home = os.path.expanduser("~")
    for c in candidates:
        if c in PROTECTED_EXACT or re.match(r"^[A-Za-z]:[/\\]?$", c):
            return True
        if c == home:
            return True
    return any(re.match(h, c) for c in candidates for h in SYSTEM_AREA_HINTS)


def is_protected_write_path(path: str) -> bool:
    """True for system OS paths that must not be written to (Windows, Program Files, /etc, etc.)."""
    if not path:
        return True
    try:
        candidates = {path, os.path.realpath(path)}
    except Exception:
        return True
    variants = set()
    for c in candidates:
        variants.add(c.replace("/", "\\"))
        variants.add(c.replace("\\", "/"))
    candidates |= variants
    # Only block Windows/Program Files/Unix system areas, allow root of drives like D:\ and user directories
    return any(re.match(h, c) for c in candidates for h in SYSTEM_AREA_HINTS[1:])


def is_app_data_path(path: str) -> bool:
    """True for the app's private settings/log directory.

    That folder holds the PBKDF2 password hash and logs; it must never be
    downloadable or writable through the LAN file manager.
    """
    if not path:
        return False
    try:
        from core.settings import get_settings_path

        base = os.path.realpath(get_settings_path().parent)
        target = os.path.realpath(path)
    except Exception:
        return False
    return target == base or target.startswith(base + os.sep)


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str) -> str:
    """Strips directories and dangerous characters from an uploaded filename."""
    # Treat both separators so traversal is blocked on every OS
    name = (name or "").replace("\\", "/").strip().lstrip(".")
    name = os.path.basename(name)
    name = re.sub(r"[<>:\"|?*\x00-\x1f/]", "_", name)
    stem, ext = os.path.splitext(name)
    if stem.upper() in _WINDOWS_RESERVED:
        stem = "_" + stem
    name = stem + ext
    return name[:180] or "upload.bin"


def sanitize_relpath(rel_path: str) -> str:
    """Sanitizes a relative path (e.g. 'MyFolder/sub/file.txt') preserving subdirectories without directory traversal."""
    rel_path = (rel_path or "").replace("\\", "/").strip().lstrip("/")
    parts = [p for p in rel_path.split("/") if p and p != "." and p != ".."]
    if not parts:
        return "upload.bin"
    clean_parts = []
    for part in parts:
        clean = sanitize_filename(part)
        if clean:
            clean_parts.append(clean)
    return os.path.join(*clean_parts) if clean_parts else "upload.bin"


def get_local_ips() -> List[str]:
    """Returns all IPv4 network interface addresses."""
    ips = ["127.0.0.1"]
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_system_drives() -> List[str]:
    """Returns available drive paths on the current operating system."""
    drives: List[str] = []
    if sys.platform == "win32":
        try:
            for part in psutil.disk_partitions(all=False):
                if part.device and part.device not in drives:
                    drives.append(part.device)
        except Exception:
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                path = f"{letter}:\\"
                if os.path.exists(path):
                    drives.append(path)
    else:
        drives.append("/")
    return drives


def is_hidden_file(entry: os.DirEntry) -> bool:
    """True if file/folder is hidden or system-reserved on Windows or POSIX."""
    name = entry.name
    # 1. Standard Unix/Dotfile hiding & Windows system prefixes
    if name.startswith(".") or name.startswith("$"):
        return True
    # 2. Known Windows system files & folders
    lower_name = name.lower()
    if lower_name in {
        "desktop.ini",
        "thumbs.db",
        "system volume information",
        "$recycle.bin",
        "pagefile.sys",
        "hiberfil.sys",
        "swapfile.sys",
        "dumpstack.log.tmp",
        "ntuser.dat",
        "ntuser.ini",
    } or lower_name.startswith("ntuser.dat{"):
        return True
    # 3. Windows file attributes check (FILE_ATTRIBUTE_HIDDEN = 0x02, FILE_ATTRIBUTE_SYSTEM = 0x04)
    try:
        stat = entry.stat(follow_symlinks=False)
        attrs = getattr(stat, "st_file_attributes", 0)
        if attrs and (attrs & 0x02 or attrs & 0x04):
            return True
    except (PermissionError, OSError):
        pass
    return False


# -----------------------------------------------------------------------------
# Streaming multipart/form-data parser (replaces the removed `cgi` module)
# -----------------------------------------------------------------------------
class MultipartParser:
    """Parses multipart uploads directly from a socket stream to disk."""

    def __init__(
        self,
        rfile,
        content_type: str,
        max_size: int = DEFAULT_MAX_UPLOAD,
        content_length: Optional[int] = None,
    ):
        match = re.search(r'boundary="?([^";]+)"?', content_type or "")
        if not match:
            raise ApiError(400, "Missing multipart boundary") from None
        self.boundary = match.group(1).encode("utf-8")
        self.rfile = rfile
        self.max_size = max_size
        self.consumed = 0
        # Bytes still expected on the wire: bounds every read so we never
        # block waiting for data that the client will never send.
        self.remaining = content_length

    def _read(self, n: int) -> bytes:
        if self.remaining is not None:
            n = min(n, self.remaining)
        if n <= 0:
            return b""
        if self.consumed + n > self.max_size:
            raise ApiError(413, "Upload exceeds the maximum allowed size") from None
        data = self.rfile.read(n)
        if not data:
            return b""
        self.consumed += len(data)
        if self.remaining is not None:
            self.remaining -= len(data)
        return data

    def parse(self, on_file: Callable[[str, str, io.BufferedIOBase], None]) -> Dict[str, str]:
        """
        Streams the body. `on_file(field_name, filename, fileobj)` is called with
        an open temp file object for every uploaded file (caller moves it).
        Returns the plain form fields.
        """
        fields: Dict[str, str] = {}
        marker = b"--" + self.boundary
        body_marker = b"\r\n--" + self.boundary
        buf = b""

        def fill(need: int) -> bool:
            nonlocal buf
            while len(buf) < need:
                chunk = self._read(1048576)
                if not chunk:
                    return False
                buf += chunk
            return True

        # --- preamble: skip to the first boundary
        while True:
            idx = buf.find(marker)
            if idx != -1:
                buf = buf[idx + len(marker):]
                break
            chunk = self._read(1048576)
            if not chunk:
                raise ApiError(400, "Malformed multipart body (no boundary)")
            buf += chunk
            # keep only the tail to avoid unbounded growth
            if len(buf) > len(marker) + 1048576:
                buf = buf[-(len(marker) + 64):]

        while True:
            # after a boundary: "--" = final, else expect CRLF then headers
            if not fill(2):
                break
            if buf.startswith(b"--"):
                break  # closing boundary
            if buf.startswith(b"\r\n"):
                buf = buf[2:]
            elif buf.startswith(b"\n"):
                buf = buf[1:]
            else:
                raise ApiError(400, "Malformed multipart body (bad boundary)")

            # --- part headers
            while True:
                idx = buf.find(b"\r\n\r\n")
                if idx != -1:
                    header_blob, buf = buf[:idx], buf[idx + 4:]
                    break
                alt = buf.find(b"\n\n")
                if alt != -1:
                    header_blob, buf = buf[:alt], buf[alt + 2:]
                    break
                chunk = self._read(4096)
                if not chunk:
                    raise ApiError(400, "Malformed multipart body (headers)")
                buf += chunk
            headers = {}
            for line in header_blob.decode("utf-8", errors="replace").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            disposition = headers.get("content-disposition", "")
            field_name = ""
            filename = None
            m = re.search(r'name="([^"]*)"', disposition)
            if m:
                field_name = m.group(1)
            m = re.search(r'filename="([^"]*)"', disposition)
            if m:
                filename = m.group(1)

            # --- part body: stream until \r\n--boundary
            if filename is not None:
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, prefix="sp_upload_", suffix=".part"
                )
                try:
                    with tmp:
                        while True:
                            idx = buf.find(body_marker)
                            if idx != -1:
                                tmp.write(buf[:idx])
                                buf = buf[idx + len(body_marker):]
                                break
                            # write everything except a possible split-marker tail
                            keep = len(body_marker) - 1
                            if len(buf) > keep:
                                tmp.write(buf[:-keep])
                                buf = buf[-keep:]
                            if not fill(len(buf) + 1):
                                raise ApiError(400, "Truncated upload")
                    on_file(field_name, filename, tmp)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except Exception:
                        pass
                    raise
            else:
                chunks = bytearray()
                keep = len(body_marker) - 1
                while True:
                    idx = buf.find(body_marker)
                    if idx != -1:
                        chunks += buf[:idx]
                        buf = buf[idx + len(body_marker):]
                        break
                    if len(chunks) + len(buf) > 1024 * 1024:
                        raise ApiError(400, "Form field too large")
                    if len(buf) > keep:
                        chunks += buf[:-keep]
                        buf = buf[-keep:]
                    if not fill(len(buf) + 1):
                        raise ApiError(400, "Truncated body")
                fields[field_name] = chunks.decode("utf-8", errors="replace")

        return fields


# -----------------------------------------------------------------------------
# PWA icon generation (lazy, cached)
# -----------------------------------------------------------------------------
_ICON_CACHE: Dict[str, bytes] = {}


def generate_app_icon(size: int = 192) -> bytes:
    """Generates the power-glyph app icon as PNG bytes (cached)."""
    key = str(size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), color=(10, 22, 40, 255))
    draw = ImageDraw.Draw(img)
    s = size
    draw.ellipse(
        (s * 0.06, s * 0.06, s * 0.94, s * 0.94),
        fill=(12, 20, 36, 255),
        outline=(34, 211, 238, 255),
        width=max(2, int(s * 0.05)),
    )
    draw.arc(
        (s * 0.22, s * 0.22, s * 0.78, s * 0.78),
        start=300,
        end=240,
        fill=(34, 211, 238, 255),
        width=max(3, int(s * 0.07)),
    )
    draw.line(
        (s * 0.5, s * 0.16, s * 0.5, s * 0.48),
        fill=(34, 211, 238, 255),
        width=max(3, int(s * 0.07)),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    _ICON_CACHE[key] = data
    return data


# -----------------------------------------------------------------------------
# Optional HTTPS support (self-signed certificate via `cryptography`)
# -----------------------------------------------------------------------------
def https_available() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except Exception:
        return False


def ensure_self_signed_cert(
    cert_dir: pathlib.Path, ips: List[str]
) -> Optional[Tuple[str, str]]:
    """Generates (or reuses) a self-signed cert covering the given IPs."""
    if not https_available():
        return None
    import datetime

    import ipaddress as _ip

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "server.crt"
    key_path = cert_dir / "server.key"

    san_ips = [i for i in ips if i != "127.0.0.1"] or ["127.0.0.1"]

    # Reuse an existing certificate when it still covers the current IPs
    if cert_path.exists() and key_path.exists():
        try:
            data = cert_path.read_bytes()
            cert = x509.load_pem_x509_certificate(data)
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            covered = {str(v.value) for v in san.value}
            if all(ip in covered for ip in san_ips):
                return str(cert_path), str(key_path)
        except Exception:
            pass

    get_logger().info("Generating new self-signed HTTPS certificate")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Shutdown Panel")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san_list: List[Any] = [x509.DNSName("localhost"), x509.IPAddress(_ip.ip_address("127.0.0.1"))]
    for ip in san_ips:
        try:
            san_list.append(x509.IPAddress(_ip.ip_address(ip)))
        except ValueError:
            continue
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        # The private key must not be readable by other local users.
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o644)
    except OSError:
        pass
    return str(cert_path), str(key_path)


# -----------------------------------------------------------------------------
# Server
# -----------------------------------------------------------------------------
class RemoteServer:
    def __init__(
        self,
        on_command: Callable[[str, int, bool], Dict[str, Any]],
        on_abort: Callable[[], Dict[str, Any]],
        token: Optional[str] = None,
        username: str = "admin",
        password: str = "admin",
        password_hash: Optional[str] = None,
        metrics_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        max_upload: int = DEFAULT_MAX_UPLOAD,
        on_lock: Optional[Callable[[str], Dict[str, Any]]] = None,
        on_unlock: Optional[Callable[[], Dict[str, Any]]] = None,
        lock_status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self.on_command = on_command
        self.on_abort = on_abort
        self.metrics_provider = metrics_provider
        self.max_upload = max_upload
        self.on_lock = on_lock
        self.on_unlock = on_unlock
        self.lock_status_provider = lock_status_provider
        self.running = False
        self.port = 8080
        self.bind = "0.0.0.0"
        self.https = False
        self.username = (username or "admin").strip()
        # Only a PBKDF2 hash is kept in memory; the plain-text password never
        # lives on the server object.
        if password_hash:
            self.password_hash = password_hash
        else:
            self.password_hash = hash_password((password or "admin").strip())
        self.token = (token or secrets.token_hex(6)).upper()
        # The token doubles as the master session. Extra sessions are created
        # by /api/auth/login and are revoked whenever credentials rotate.
        self.sessions: Dict[str, float] = {self.token: time.time()}
        self.started_at: Optional[int] = None
        self.clients: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._beacon: Optional[UDPBeacon] = None
        self._rate_limits: Dict[str, List[float]] = {}
        self._login_failures: Dict[str, List[float]] = {}  # brute-force tracking
        self._lock = threading.Lock()
        self._log_id = 1
        self._qr_cache: Dict[str, Any] = {}
        self._mobile_html_cache: Tuple[float, bytes] = (0.0, b"")
        self._proc_primed = False

    def set_lock_handlers(
        self,
        on_lock: Optional[Callable[[str], Dict[str, Any]]] = None,
        on_unlock: Optional[Callable[[], Dict[str, Any]]] = None,
        lock_status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self.on_lock = on_lock
        self.on_unlock = on_unlock
        self.lock_status_provider = lock_status_provider

    # ------------------------------------------------------------------
    # Credentials & Session management
    # ------------------------------------------------------------------
    def set_credentials(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        password_hash: Optional[str] = None,
    ):
        """Updates credentials and revokes every existing session.

        Changing the password (or rotating the token) must not leave previously
        authenticated phones connected.
        """
        with self._lock:
            changed = False
            if username is not None and username.strip() and username.strip() != self.username:
                self.username = username.strip()
                changed = True
            if password_hash:
                self.password_hash = password_hash
                changed = True
            elif password is not None and password.strip():
                self.password_hash = hash_password(password.strip())
                changed = True
            if changed:
                self.revoke_sessions_locked()
            self._qr_cache.clear()

    def revoke_sessions_locked(self):
        """Rotates the master token and drops all login sessions.

        Caller must hold ``self._lock``.
        """
        self.token = secrets.token_hex(6).upper()
        self.sessions = {self.token: time.time()}
        self._qr_cache.clear()

    def revoke_sessions(self) -> str:
        with self._lock:
            self.revoke_sessions_locked()
            return self.token

    def verify_credentials(self, username: str, password: str) -> bool:
        with self._lock:
            u_ok = secrets.compare_digest((username or "").strip(), self.username)
            stored = self.password_hash
        # PBKDF2 is intentionally slow: run it outside the lock.
        p_ok = verify_password((password or "").strip(), stored)
        return u_ok and p_ok

    def create_session(self) -> str:
        with self._lock:
            sess_token = secrets.token_hex(16).upper()
            self.sessions[sess_token] = time.time()
            cutoff = time.time() - 30 * 86400  # 30 days retention
            self.sessions = {k: v for k, v in self.sessions.items() if v > cutoff}
            return sess_token

    def is_valid_token(self, token: str) -> bool:
        if not token:
            return False
        clean = token.strip().upper()
        cutoff = time.time() - 30 * 86400  # sessions expire after 30 days
        with self._lock:
            if secrets.compare_digest(clean, self.token):
                return True
            for st, created in list(self.sessions.items()):
                if created < cutoff:
                    self.sessions.pop(st, None)
                    continue
                if secrets.compare_digest(clean, st):
                    return True
            return False

    def rotate_token(self) -> str:
        """Issues a new master token and invalidates every previous session."""
        with self._lock:
            self.revoke_sessions_locked()
            return self.token

    def get_scheme(self) -> str:
        return "https" if self.https else "http"

    def is_rate_limited(self, ip: str) -> bool:
        if ip in ("127.0.0.1", "::1", "localhost"):
            return False
        now = time.time()
        with self._lock:
            hits = self._rate_limits.setdefault(ip, [])
            hits[:] = [t for t in hits if now - t < 60.0]
            # Opportunistic cleanup of idle IPs (prevents unbounded growth)
            if len(self._rate_limits) > 256:
                for other in list(self._rate_limits.keys()):
                    lst = self._rate_limits[other]
                    if not lst or now - lst[-1] > 600.0:
                        self._rate_limits.pop(other, None)
            if len(hits) >= RATE_LIMIT_PER_MIN:
                return True
            hits.append(now)
            return False

    # -- Login brute-force protection ----------------------------------
    def is_login_locked(self, ip: str) -> bool:
        """Returns True if the IP is temporarily locked out due to too many
        failed login attempts. Unlike rate limiting, this applies to ALL IPs
        including localhost (the desktop app authenticates via tokens, not login)."""
        now = time.time()
        with self._lock:
            fails = self._login_failures.get(ip, [])
            # Keep only recent failures
            fails = [t for t in fails if now - t < LOGIN_LOCKOUT_SECS]
            self._login_failures[ip] = fails
            return len(fails) >= LOGIN_MAX_FAILURES

    def record_login_failure(self, ip: str):
        """Records a failed login attempt for the IP."""
        now = time.time()
        with self._lock:
            fails = self._login_failures.setdefault(ip, [])
            fails[:] = [t for t in fails if now - t < LOGIN_LOCKOUT_SECS]
            fails.append(now)
            # Cleanup old IPs
            if len(self._login_failures) > 256:
                for other in list(self._login_failures.keys()):
                    lst = self._login_failures[other]
                    if not lst or now - lst[-1] > LOGIN_LOCKOUT_SECS:
                        self._login_failures.pop(other, None)

    def track_client(self, ip: str, ua: str, action: Optional[str] = None, auth: bool = True):
        now = int(time.time())
        with self._lock:
            for c in self.clients:
                if c["ip"] == ip:
                    c["lastSeen"] = now
                    c["requests"] += 1
                    if action:
                        c["lastAction"] = action
                    c["authenticated"] = auth
                    return
            self.clients.insert(
                0,
                {
                    "id": f"client-{len(self.clients) + 1}",
                    "ip": ip,
                    "userAgent": ua[:40] if ua else "Unknown",
                    "firstSeen": now,
                    "lastSeen": now,
                    "requests": 1,
                    "lastAction": action,
                    "authenticated": auth,
                },
            )
            self.clients = self.clients[:30]

    def add_log(self, ip: str, text: str, ok: bool):
        with self._lock:
            self.logs.insert(
                0,
                {"id": self._log_id, "time": int(time.time()), "ip": ip, "text": text, "ok": ok},
            )
            self._log_id += 1
            self.logs = self.logs[:50]
        get_logger().info("[%s] %s (%s)", ip, text, "ok" if ok else "fail")

    # ------------------------------------------------------------------
    # QR code (cached)
    # ------------------------------------------------------------------
    def build_url(self, ip: str) -> str:
        return f"{self.get_scheme()}://{ip}:{self.port}/"

    def get_qr_data_uri(self, base_url: Optional[str] = None) -> str:
        if qrcode is None:
            return ""
        if not base_url:
            non_local = [ip for ip in get_local_ips() if ip != "127.0.0.1"]
            ip = non_local[0] if non_local else "127.0.0.1"
            base_url = self.build_url(ip)

        cache_key = base_url
        with self._lock:
            if self._qr_cache.get("key") == cache_key:
                return self._qr_cache["uri"]

        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(base_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        import base64

        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        with self._lock:
            self._qr_cache["key"] = cache_key
            self._qr_cache["uri"] = uri
        return uri

    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        scheme = self.get_scheme()
        if self.bind != "0.0.0.0":
            ips_to_show = [self.bind]
        else:
            ips_to_show = get_local_ips()
            # If 0.0.0.0, prioritize the real network IP over localhost for copying
            if len(ips_to_show) > 1 and "127.0.0.1" in ips_to_show:
                ips_to_show.remove("127.0.0.1")
                ips_to_show.append("127.0.0.1")
                
        urls = [f"{scheme}://{ip}:{self.port}/" for ip in ips_to_show]
        return {
            "running": self.running,
            "bind": self.bind,
            "port": self.port,
            "https": self.https,
            "httpsAvailable": https_available(),
            "username": self.username,
            "token": self.token,
            "urls": urls,
            "qrDataUri": self.get_qr_data_uri(),
            "startedAt": self.started_at,
            "clients": list(self.clients),
            "logs": list(self.logs),
            "host": socket.gethostname(),
            "version": __version__,
        }

    # ------------------------------------------------------------------
    # Mobile page (static, cached by mtime)
    # ------------------------------------------------------------------
    def _load_mobile_html(self) -> bytes:
        path = WEB_DIR / "mobile.html"
        try:
            mtime = path.stat().st_mtime
            cached_at, cached = self._mobile_html_cache
            if cached_at == mtime and cached:
                return cached
            data = path.read_bytes()
            self._mobile_html_cache = (mtime, data)
            return data
        except Exception as e:
            get_logger().error("mobile.html missing: %s", e)
            return (
                "<!DOCTYPE html><html><body style='font-family:sans-serif;background:#0b0f19;"
                "color:#fff;padding:40px;text-align:center'><h2>Shutdown Panel</h2>"
                "<p>mobile.html not found next to gui/web.</p></body></html>"
            ).encode("utf-8")

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------
    def start(
        self, bind: str = "0.0.0.0", port: int = 8080, https: bool = False
    ) -> Dict[str, Any]:
        if self.running:
            return self.get_status()

        self.bind = bind
        self.port = port
        self.https = bool(https and https_available())
        server_instance = self

        class Handler(_RequestHandler):
            remote = server_instance

        class SilentThreadingServer(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True
            timeout = 10.0

            def handle_error(self, request, client_address):
                cls, exc, _tb = sys.exc_info()
                if isinstance(
                    exc,
                    (
                        ConnectionResetError,
                        ConnectionAbortedError,
                        BrokenPipeError,
                        TimeoutError,
                    ),
                ):
                    return
                if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (
                    10053,
                    10054,
                    10038,
                ):
                    return
                get_logger().warning(
                    "Handler error from %s: %s", client_address, exc, exc_info=True
                )

        try:
            self._server = SilentThreadingServer((bind, port), Handler)
            self.port = self._server.server_port
            if self.https:
                import ssl

                from core.settings import get_settings_path

                cert_dir = get_settings_path().parent / "ssl"
                cert = ensure_self_signed_cert(cert_dir, get_local_ips())
                if cert:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.load_cert_chain(cert[0], cert[1])
                    self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
                else:
                    self.https = False
        except Exception as e:
            self.running = False
            raise RuntimeError(f"Could not bind server to {bind}:{port}: {e}")

        self.running = True
        self.started_at = int(time.time())
        self._prime_process_counters()
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="LANServerThread"
        )
        self._thread.start()

        # Start UDP discovery beacon so clients can auto-discover this server
        try:
            self._beacon = UDPBeacon(
                server_name=socket.gethostname(),
                server_port=port,
            )
            self._beacon.start()
        except Exception as e:
            get_logger().warning("UDP beacon failed to start: %s", e)

        self.add_log("127.0.0.1", f"Server started on {bind}:{port} ({self.get_scheme()})", True)
        return self.get_status()

    def stop(self) -> Dict[str, Any]:
        # Stop discovery beacon
        if self._beacon:
            try:
                self._beacon.stop()
            except Exception:
                pass
            self._beacon = None

        srv, self._server = self._server, None
        if srv:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass
        self._thread = None
        self.running = False
        self.started_at = None
        self.add_log("127.0.0.1", "Server stopped", True)
        return self.get_status()

    def _prime_process_counters(self):
        """First psutil cpu_percent call returns 0; prime it so the mobile UI gets real values."""
        if self._proc_primed:
            return
        try:
            for _ in psutil.process_iter(["cpu_percent"]):
                pass
            self._proc_primed = True
        except Exception:
            pass


# -----------------------------------------------------------------------------
# HTTP request handler
# -----------------------------------------------------------------------------
PUBLIC_GET_PATHS = {
    "/",
    "/index.html",
    "/api/status",
    "/api/health",
    "/manifest.webmanifest",
    "/icon.png",
    "/favicon.ico",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
}


class _RequestHandler(BaseHTTPRequestHandler):
    remote: RemoteServer = None  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"
    server_version = "ShutdownPanel/" + __version__

    def setup(self):
        super().setup()
        try:
            self.request.settimeout(10.0)
        except Exception:
            pass

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # requests are logged selectively via add_log()

    # -- helpers -------------------------------------------------------
    def _security_headers(self):
        """Baseline hardening for every response served to a browser."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; font-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'",
        )

    def send_json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, content_type: str, data: bytes, cache: bool = False, filename: Optional[str] = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        if filename:
            safe = urllib.parse.quote(filename)
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{safe}"; filename*=UTF-8\'\'{safe}',
            )
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ApiError(400, "Invalid Content-Length")
        if length <= 0:
            return {}
        if length > 10 * 1024 * 1024:
            raise ApiError(413, "JSON body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "Invalid JSON body")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON object expected")
        return data

    def check_auth(self) -> bool:
        rs = self.remote
        auth_header = self.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif auth_header.startswith("Basic "):
            try:
                import base64

                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                if ":" in decoded:
                    u, p = decoded.split(":", 1)
                    if rs.verify_credentials(u, p):
                        rs.track_client(
                            self.client_address[0],
                            self.headers.get("User-Agent", "Browser"),
                            None,
                            True,
                        )
                        return True
            except Exception:
                pass

        if not token:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = q.get("token", [""])[0].strip()
        if not token:
            token = self.headers.get("X-Auth-Token", "").strip()

        is_valid = rs.is_valid_token(token)
        rs.track_client(
            self.client_address[0],
            self.headers.get("User-Agent", "Browser"),
            None,
            is_valid,
        )
        return is_valid

    # -- dispatch ------------------------------------------------------
    def do_GET(self):
        self._safely(self._handle_get)

    def do_POST(self):
        self._safely(self._handle_post)

    def do_OPTIONS(self):
        # Same-origin app: no cross-origin API access is needed.
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _safely(self, fn):
        try:
            fn()
        except ApiError as e:
            # The request body may be partially read: never reuse this connection.
            self.close_connection = True
            try:
                self.send_json(e.status, {"ok": False, "error": e.message})
            except Exception:
                pass
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:  # pragma: no cover - defensive
            get_logger().error("Unhandled request error: %s", e, exc_info=True)
            self.close_connection = True
            try:
                self.send_json(500, {"ok": False, "error": "Internal server error"})
            except Exception:
                pass

    # -- GET routes ----------------------------------------------------
    def _handle_get(self):
        rs = self.remote
        ip = self.client_address[0]
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Public: mobile web app
        if path in ("/", "/index.html"):
            self.send_bytes("text/html; charset=utf-8", rs._load_mobile_html())
            return
            
        # Public: themes and fonts
        if path == "/themes.css":
            css_path = WEB_DIR / "themes.css"
            if css_path.exists():
                self.send_bytes("text/css; charset=utf-8", css_path.read_bytes(), cache=True)
            else:
                self.send_json(404, {"ok": False, "error": "Not found"})
            return
            
        if path.startswith("/fonts/"):
            # Resolve and confine to gui/web/fonts: "/fonts/../x.woff2" must
            # not escape the web root.
            fonts_dir = (WEB_DIR / "fonts").resolve()
            candidate = (WEB_DIR / path.lstrip("/")).resolve()
            try:
                candidate.relative_to(fonts_dir)
            except ValueError:
                candidate = None
            if (
                candidate is not None
                and candidate.is_file()
                and candidate.suffix.lower() == ".woff2"
            ):
                self.send_bytes("font/woff2", candidate.read_bytes(), cache=True)
            else:
                self.send_json(404, {"ok": False, "error": "Not found"})
            return

        # Public: health / basic status (no sensitive data)
        if path == "/api/status":
            self.send_json(
                200,
                {
                    "ok": True,
                    "running": True,
                    "scheme": rs.get_scheme(),
                    "port": rs.port,
                    "host": socket.gethostname(),
                    "version": __version__,
                },
            )
            return
        if path == "/api/health":
            self.send_json(200, {"ok": True})
            return

        # Public: PWA assets
        if path == "/manifest.webmanifest":
            manifest = {
                "name": "Shutdown Panel Remote",
                "short_name": "SP Remote",
                "start_url": "./",
                "display": "standalone",
                "background_color": "#0b0f19",
                "theme_color": "#0b0f19",
                "description": "Remote control for Shutdown Panel",
                "icons": [
                    {"src": "/icon.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/icon.png", "sizes": "512x512", "type": "image/png"},
                ],
            }
            self.send_bytes(
                "application/manifest+json",
                json.dumps(manifest).encode("utf-8"),
                cache=True,
            )
            return
        if path in ("/icon.png", "/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            self.send_bytes("image/png", generate_app_icon(192), cache=True)
            return

        # Everything else requires authentication
        if not self.check_auth():
            rs.add_log(ip, f"Unauthorized GET attempt: {path}", False)
            self.close_connection = True
            self.send_json(401, {"ok": False, "error": "Invalid token"})
            return
        if rs.is_rate_limited(ip):
            self.send_json(429, {"ok": False, "error": "Rate limit exceeded"})
            return

        # -- QR code (AUTHENTICATED: it embeds the access token!)
        if path == "/api/qr":
            if qrcode is None:
                raise ApiError(500, "qrcode library not installed")
            target_ip = query.get("ip", [""])[0]
            if not target_ip or not re.match(r"^[0-9a-fA-F.:]+$", target_ip):
                non_local = [i for i in get_local_ips() if i != "127.0.0.1"]
                target_ip = non_local[0] if non_local else "127.0.0.1"
            url = rs.build_url(target_ip)
            qr = qrcode.QRCode(box_size=8, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, "PNG")
            self.send_bytes("image/png", buf.getvalue(), cache=False)
            return

        # -- System summary
        if path == "/api/system/summary":
            if rs.metrics_provider:
                data = rs.metrics_provider()
            else:
                from core.metrics import MetricsCollector

                data = MetricsCollector().sample()
            if isinstance(data, dict):
                data.setdefault("ok", True)
            self.send_json(200, data)
            return

        # -- File system: list
        if path == "/api/fs/list":
            self._fs_list(query)
            return
        if path == "/api/fs/download":
            self._fs_download(query)
            return
        if path == "/api/fs/download_zip":
            self._fs_download_zip(query)
            return

        # -- Screen
        if path == "/api/screen/stream":
            self._screen_stream(query)
            return
        if path == "/api/screen/frame":
            scale = as_float(query.get("scale", ["1.0"])[0], 1.0, 0.1, 1.0)
            quality = as_int(query.get("q", ["80"])[0], 80, 10, 95)
            frame = ScreenStreamer.capture_frame(scale=scale, quality=quality)
            self.send_bytes("image/jpeg", frame)
            return
        if path == "/api/screen/size":
            self.send_json(200, InputController.get_screen_size())
            return

        # -- Media volume
        if path == "/api/media/volume":
            vol = InputController.get_volume_percent()
            self.send_json(200, {"ok": True, "volume": vol if vol is not None else 50})
            return

        # -- Clipboard
        if path == "/api/clipboard":
            if not clipboard_supported():
                self.send_json(200, {"ok": False, "supported": False, "text": None})
                return
            self.send_json(
                200, {"ok": True, "supported": True, "text": get_clipboard_text() or ""}
            )
            return

        # -- Lock status
        if path == "/api/lock/status":
            if rs.lock_status_provider:
                self.send_json(200, rs.lock_status_provider())
            else:
                self.send_json(200, {"ok": True, "locked": False, "message": ""})
            return

        self.send_json(404, {"ok": False, "error": "Not found"})

    # -- POST routes ---------------------------------------------------
    def _handle_post(self):
        rs = self.remote
        ip = self.client_address[0]
        ua = self.headers.get("User-Agent", "App")
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if rs.is_rate_limited(ip):
            self.send_json(429, {"ok": False, "error": "Rate limit exceeded"})
            return

        # Public authentication endpoint
        if path == "/api/auth/login":
            # Brute-force protection: reject early if IP is locked out
            if rs.is_login_locked(ip):
                rs.add_log(ip, "Login blocked (too many failed attempts)", False)
                self.send_json(429, {"ok": False, "error": "Too many failed attempts. Try again later."})
                return
            payload = self.read_json_body()
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", "")).strip()
            if rs.verify_credentials(username, password):
                session_token = rs.create_session()
                rs.track_client(ip, ua, "login", True)
                rs.add_log(ip, f"User '{username}' authenticated successfully", True)
                self.send_json(200, {"ok": True, "token": session_token, "username": username})
            else:
                rs.record_login_failure(ip)
                rs.track_client(ip, ua, "login_failed", False)
                rs.add_log(ip, f"Failed login attempt for user '{username}'", False)
                self.send_json(401, {"ok": False, "error": "Invalid username or password"})
            return

        if not self.check_auth():
            rs.add_log(ip, f"Unauthorized POST attempt: {path}", False)
            self.close_connection = True
            self.send_json(401, {"ok": False, "error": "Invalid access credentials"})
            return

        # -- File upload (multipart, streamed to disk)
        if path == "/api/fs/upload":
            self._fs_upload()
            return

        payload = self.read_json_body()

        if path == "/api/command":
            action = str(payload.get("action", "shutdown"))
            if action == "custom_lock":
                msg = str(payload.get("message", "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب")).strip()
                res = rs.on_lock(msg) if rs.on_lock else {"ok": False, "error": "No lock handler"}
                rs.track_client(ip, ua, "custom_lock", res.get("ok", True))
                rs.add_log(ip, f"Executed remote custom lock: {msg}", res.get("ok", True))
                self.send_json(200, res)
                return
            delay = as_int(payload.get("delaySecs", 0), 0, 0, 86400)
            force = bool(payload.get("force", False))
            res = rs.on_command(action, delay, force)
            rs.track_client(ip, ua, action, True)
            rs.add_log(ip, f"Executed remote {action} (delay={delay}s)", res.get("ok", True))
            self.send_json(200, res)
            return

        if path == "/api/abort":
            res = rs.on_abort()
            rs.track_client(ip, ua, "abort", True)
            rs.add_log(ip, "Remote abort requested", res.get("ok", True))
            self.send_json(200, res)
            return

        if path == "/api/lock/activate":
            msg = str(payload.get("message", "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب")).strip()
            if rs.on_lock:
                res = rs.on_lock(msg)
            else:
                res = {"ok": False, "error": "Lock screen handler not configured"}
            rs.track_client(ip, ua, "lock_activate", res.get("ok", True))
            rs.add_log(ip, f"Remote lock activated: {msg}", res.get("ok", True))
            self.send_json(200, res)
            return

        if path == "/api/lock/unlock":
            if rs.on_unlock:
                res = rs.on_unlock()
            else:
                res = {"ok": False, "error": "Unlock handler not configured"}
            rs.track_client(ip, ua, "lock_unlock", res.get("ok", True))
            rs.add_log(ip, "Remote lock deactivated", res.get("ok", True))
            self.send_json(200, res)
            return

        if path == "/api/input/mouse":
            self._input_mouse(payload)
            return
        if path == "/api/input/keyboard":
            self._input_keyboard(payload)
            return
        if path == "/api/media/control":
            self._media_control(payload)
            return

        if path == "/api/fs/create_dir":
            self._fs_create_dir(payload)
            return
        if path == "/api/fs/open":
            self._fs_open(payload)
            return
        if path == "/api/fs/delete":
            self._fs_delete(payload)
            return
        if path == "/api/fs/rename":
            self._fs_rename(payload)
            return

        if path == "/api/proc/list":
            self._proc_list()
            return
        if path == "/api/proc/kill":
            self._proc_kill(payload)
            return

        if path == "/api/wol":
            mac = str(payload.get("mac", ""))
            broadcast = str(payload.get("broadcast", "255.255.255.255"))
            if not wol.normalize_mac(mac):
                raise ApiError(400, "Invalid MAC address")
            if not re.match(r"^[0-9.]+$", broadcast):
                raise ApiError(400, "Invalid broadcast address")
            ok = wol.wake(mac, broadcast)
            rs.add_log(ip, f"WoL sent to {mac}", ok)
            self.send_json(200, {"ok": ok, "mac": wol.normalize_mac(mac)})
            return

        if path == "/api/clipboard":
            if not clipboard_supported():
                self.send_json(200, {"ok": False, "supported": False})
                return
            text = payload.get("text", "")
            if not isinstance(text, str) or len(text) > 1024 * 1024:
                raise ApiError(400, "Invalid clipboard text")
            self.send_json(200, {"ok": set_clipboard_text(text), "supported": True})
            return

        if path == "/api/system/open_url":
            import webbrowser
            url = str(payload.get("url", "")).strip()
            if url.startswith("http://") or url.startswith("https://"):
                try:
                    webbrowser.open(url)
                    self.send_json(200, {"ok": True})
                except Exception as e:
                    self.send_json(500, {"ok": False, "error": str(e)})
            else:
                # auto-add https if missing
                try:
                    webbrowser.open("https://" + url if not url.startswith("http") else url)
                    self.send_json(200, {"ok": True})
                except Exception as e:
                    self.send_json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/system/brightness":
            val = as_int(payload.get("brightness", payload.get("percent", 50)), 50, 0, 100)
            ok = InputController.set_brightness_percent(val)
            self.send_json(200, {"ok": ok, "brightness": val})
            return

        self.send_json(404, {"ok": False, "error": "Unknown endpoint"})

    # ------------------------------------------------------------------
    # Route implementations
    # ------------------------------------------------------------------
    def _fs_list(self, query):
        target_path = query.get("path", [""])[0].strip()
        drives = get_system_drives()

        if not target_path:
            items = [
                {"name": d, "path": d, "isDir": True, "size": 0, "mtime": 0}
                for d in drives
            ]
            self.send_json(
                200,
                {"ok": True, "currentPath": "", "drives": drives, "breadcrumbs": [], "items": items},
            )
            return

        if not os.path.exists(target_path):
            self.send_json(404, {"ok": False, "error": "Path does not exist"})
            return
        if not os.path.isdir(target_path):
            self.send_json(400, {"ok": False, "error": "Not a directory"})
            return

        try:
            items = []
            with os.scandir(target_path) as entries:
                for entry in entries:
                    if is_hidden_file(entry):
                        continue
                    try:
                        stat = entry.stat()
                        items.append(
                            {
                                "name": entry.name,
                                "path": entry.path,
                                "isDir": entry.is_dir(),
                                "size": stat.st_size if not entry.is_dir() else 0,
                                "mtime": int(stat.st_mtime),
                            }
                        )
                    except (PermissionError, OSError):
                        continue
            items.sort(key=lambda x: (not x["isDir"], x["name"].lower()))

            norm = os.path.abspath(target_path)
            parts = norm.split(os.sep)
            crumbs = []
            accum = ""
            for idx, p in enumerate(parts):
                if not p:
                    continue
                if idx == 0 and sys.platform == "win32":
                    accum = p + os.sep
                elif accum:
                    accum = os.path.join(accum, p)
                else:
                    accum = os.sep + p  # POSIX absolute paths start with "/"
                crumbs.append({"name": p, "path": accum})

            self.send_json(
                200,
                {
                    "ok": True,
                    "currentPath": norm,
                    "drives": drives,
                    "breadcrumbs": crumbs,
                    "items": items,
                },
            )
        except PermissionError:
            self.send_json(403, {"ok": False, "error": "Access denied"})
        except OSError as e:
            self.send_json(500, {"ok": False, "error": str(e)})

    def _fs_download(self, query):
        file_path = query.get("path", [""])[0].strip()
        if is_app_data_path(file_path):
            self.send_json(403, {"ok": False, "error": "Access denied"})
            return
        if not file_path or not os.path.isfile(file_path):
            self.send_json(404, {"ok": False, "error": "File not found"})
            return
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"
        try:
            file_size = os.path.getsize(file_path)
            f = open(file_path, "rb")
        except OSError as e:
            self.send_json(500, {"ok": False, "error": str(e)})
            return
        try:
            safe_fn = urllib.parse.quote(filename)
            disp = f'attachment; filename="{safe_fn}"; filename*=UTF-8\'\'{safe_fn}'

            # HTTP Range support for resumable downloads
            range_header = self.headers.get("Range", "").strip()
            start = 0
            end = file_size - 1
            is_partial = False

            if range_header.startswith("bytes=") and file_size > 0:
                try:
                    range_spec = range_header[6:].strip()
                    if range_spec.endswith("-"):
                        start = int(range_spec[:-1])
                    elif "-" in range_spec:
                        parts = range_spec.split("-", 1)
                        start = int(parts[0])
                        end = int(parts[1]) if parts[1] else file_size - 1
                    if 0 <= start <= end < file_size:
                        is_partial = True
                    else:
                        # Invalid range
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                except (ValueError, IndexError):
                    pass  # ignore malformed Range, fall through to full download

            content_length = end - start + 1
            if is_partial:
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            else:
                self.send_response(200)

            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", disp)
            self.end_headers()

            if start > 0:
                f.seek(start)

            remaining = content_length
            chunk_size = 256 * 1024
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                data = f.read(to_read)
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)

            self.remote.add_log(self.client_address[0], f"Downloaded {filename}", True)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            f.close()

    def _fs_download_zip(self, query):
        folder_path = query.get("path", [""])[0].strip()
        if not folder_path or not os.path.isdir(folder_path):
            self.send_json(404, {"ok": False, "error": "Directory not found"})
            return
        from core.settings import get_settings_path

        base = os.path.realpath(get_settings_path().parent)
        target = os.path.realpath(folder_path)
        if target == base or base.startswith(target + os.sep):
            self.send_json(403, {"ok": False, "error": "Access denied"})
            return

        folder_name = os.path.basename(folder_path.rstrip(os.sep)) or "archive"
        tmp_path = None
        try:
            # Stream to a temp file first: no RAM blow-up for large folders
            fd, tmp_path = tempfile.mkstemp(prefix="sp_zip_", suffix=".zip")
            total = 0
            with os.fdopen(fd, "wb") as raw:
                with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(folder_path):
                        for f in files:
                            full_p = os.path.join(root, f)
                            rel_p = os.path.relpath(full_p, folder_path)
                            try:
                                total += os.path.getsize(full_p)
                                if total > DEFAULT_MAX_ZIP:
                                    raise ApiError(
                                        413, "Folder too large to zip (limit 2 GB)"
                                    )
                                zf.write(full_p, rel_p)
                            except ApiError:
                                raise
                            except Exception:
                                continue

            size = os.path.getsize(tmp_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            safe_fn = urllib.parse.quote(f"{folder_name}.zip")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{safe_fn}"; filename*=UTF-8\'\'{safe_fn}',
            )
            self.end_headers()
            with open(tmp_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, length=256 * 1024)
            self.remote.add_log(self.client_address[0], f"Downloaded ZIP of {folder_name}", True)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except ApiError:
            raise
        except Exception as e:
            self.send_json(500, {"ok": False, "error": str(e)})
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _fs_upload(self):
        rs = self.remote
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ApiError(400, "Multipart form data expected")

        uploaded: List[Dict[str, Any]] = []

        def on_file(field_name: str, filename: str, fileobj) -> None:
            safe_name = sanitize_relpath(filename)
            uploaded.append(
                {"field": field_name, "filename": safe_name, "tmp": fileobj.name}
            )

        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_length = None
        if content_length is not None and content_length > rs.max_upload:
            raise ApiError(413, "Upload exceeds the maximum allowed size") from None

        parser = MultipartParser(
            self.rfile, content_type, max_size=rs.max_upload,
            content_length=content_length,
        )
        fields = parser.parse(on_file)

        # Drain any trailing bytes (final CRLF) so keep-alive stays consistent
        try:
            leftover = parser.remaining or 0
            while leftover > 0:
                chunk = self.rfile.read(min(1048576, leftover))
                if not chunk:
                    break
                leftover -= len(chunk)
        except Exception:
            self.close_connection = True

        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        target_dir = (
            fields.get("target_path", "").strip()
            or query.get("target_path", [""])[0].strip()
            or query.get("path", [""])[0].strip()
        )
        if not target_dir or not os.path.isdir(target_dir):
            for u in uploaded:
                try:
                    os.unlink(u["tmp"])
                except Exception:
                    pass
            raise ApiError(400, "Invalid target directory")
        if is_protected_write_path(target_dir) or is_app_data_path(target_dir):
            for u in uploaded:
                try:
                    os.unlink(u["tmp"])
                except Exception:
                    pass
            raise ApiError(403, "Writing into system directories is not allowed")

        results = []
        for u in uploaded:
            dest = os.path.join(target_dir, u["filename"])
            dest_dir = os.path.dirname(dest)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            try:
                shutil.move(u["tmp"], dest)
                results.append(u["filename"])
                rs.add_log(
                    self.client_address[0], f"Uploaded {u['filename']} to {target_dir}", True
                )
            except Exception as e:
                try:
                    os.unlink(u["tmp"])
                except Exception:
                    pass
                rs.add_log(
                    self.client_address[0], f"Upload failed: {u['filename']} ({e})", False
                )

        if not results:
            raise ApiError(400, "No file uploaded")
        self.send_json(200, {"ok": True, "files": results, "path": target_dir})

    def _fs_open(self, payload):
        target = str(payload.get("path", "")).strip()
        if is_app_data_path(target):
            raise ApiError(403, "Access denied")
        if not target or not os.path.exists(target):
            raise ApiError(404, "File not found")
        try:
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            self.remote.add_log(
                self.client_address[0], f"Opened on computer: {os.path.basename(target)}", True
            )
            self.send_json(200, {"ok": True, "path": target, "name": os.path.basename(target)})
        except Exception as e:
            self.remote.add_log(self.client_address[0], f"Failed to open file: {e}", False)
            self.send_json(500, {"ok": False, "error": str(e)})

    def _fs_create_dir(self, payload):
        parent = str(payload.get("parent_path", ""))
        name = str(payload.get("name", "")).strip()
        if not parent or not os.path.isdir(parent) or not name:
            raise ApiError(400, "Invalid parameters")
        if is_protected_write_path(parent):
            raise ApiError(403, "Creating folders in system directories is not allowed")
        name = sanitize_filename(name)
        new_dir = os.path.join(parent, name)
        os.makedirs(new_dir, exist_ok=True)
        self.remote.add_log(self.client_address[0], f"Created folder {name}", True)
        self.send_json(200, {"ok": True, "path": new_dir})

    def _fs_delete(self, payload):
        rs = self.remote
        target = str(payload.get("path", ""))
        permanent = bool(payload.get("permanent", False))
        # Protection check FIRST (never reveal/act on system paths)
        if not target or is_protected_path(target) or is_app_data_path(target):
            self.send_json(403, {"ok": False, "error": "This path is protected"})
            return
        if not os.path.exists(target):
            self.send_json(404, {"ok": False, "error": "Target not found"})
            return

        try:
            if permanent:
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                rs.add_log(self.client_address[0], f"Permanently deleted {target}", True)
                self.send_json(200, {"ok": True, "permanent": True})
                return
            if send2trash is None:
                # No trash library available: refuse rather than destroy data
                self.send_json(
                    501,
                    {"ok": False, "error": "Safe delete unavailable (send2trash missing)"},
                )
                return
            send2trash(target)
            rs.add_log(self.client_address[0], f"Moved to trash {target}", True)
            self.send_json(200, {"ok": True, "permanent": False})
        except ApiError:
            raise
        except Exception as e:
            self.send_json(500, {"ok": False, "error": str(e)})

    def _fs_rename(self, payload):
        target = str(payload.get("path", ""))
        new_name = str(payload.get("newName", "")).strip()
        if not target or not os.path.exists(target):
            raise ApiError(404, "Target not found")
        new_name = sanitize_filename(new_name)
        if not new_name:
            raise ApiError(400, "Invalid new name")
        parent = os.path.dirname(target)
        if is_protected_path(target):
            raise ApiError(403, "This path is protected")
        dest = os.path.join(parent, new_name)
        if os.path.exists(dest):
            raise ApiError(409, "An item with this name already exists")
        os.rename(target, dest)
        self.remote.add_log(self.client_address[0], f"Renamed to {new_name}", True)
        self.send_json(200, {"ok": True, "path": dest})

    def _proc_list(self):
        procs = []
        for p in psutil.process_iter(
            ["pid", "name", "username", "cpu_percent", "memory_percent"]
        ):
            try:
                info = p.info
                procs.append(
                    {
                        "pid": info["pid"],
                        "name": (info["name"] or "")[:40],
                        "user": (info["username"] or "").split("\\")[-1][:20],
                        "cpu": round(info["cpu_percent"] or 0.0, 1),
                        "mem": round(info["memory_percent"] or 0.0, 1),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        self.send_json(200, {"ok": True, "items": procs[:60], "total": len(procs)})

    def _proc_kill(self, payload):
        pid = as_int(payload.get("pid", 0), 0, 1, 4194304)
        if pid == os.getpid():
            raise ApiError(403, "Refusing to kill the panel itself")
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.5)
            self.remote.add_log(self.client_address[0], f"Killed process {name} ({pid})", True)
            self.send_json(200, {"ok": True, "pid": pid, "name": name})
        except psutil.NoSuchProcess:
            self.send_json(404, {"ok": False, "error": "Process not found"})
        except psutil.AccessDenied:
            self.send_json(403, {"ok": False, "error": "Access denied (try running as admin)"})
        except psutil.TimeoutExpired:
            self.send_json(500, {"ok": False, "error": "Process did not terminate"})

    def _screen_stream(self, query):
        fps = as_int(query.get("fps", ["15"])[0], 15, 1, 30)
        scale = as_float(query.get("scale", ["0.6"])[0], 0.6, 0.1, 1.0)
        quality = as_int(query.get("q", ["55"])[0], 55, 10, 95)
        max_secs = as_int(query.get("max", ["1800"])[0], 1800, 10, 7200)

        # MJPEG has no Content-Length: the connection must close afterwards.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            for chunk in ScreenStreamer.generate_mjpeg_frames(
                fps=fps, scale=scale, quality=quality, max_duration_secs=max_secs
            ):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _input_mouse(self, payload: Dict[str, Any]):
        action = str(payload.get("action", "")).strip().lower()
        if action == "move":
            dx = as_float(payload.get("dx", 0), 0, -5000, 5000)
            dy = as_float(payload.get("dy", 0), 0, -5000, 5000)
            InputController.mouse_move_rel(dx, dy)
            self.send_json(200, {"ok": True})
            return
        if action == "click":
            btn = str(payload.get("button", "left")).lower()
            dbl = bool(payload.get("double", False))
            InputController.mouse_click(btn, dbl)
            self.send_json(200, {"ok": True})
            return
        if action == "down":
            btn = str(payload.get("button", "left")).lower()
            InputController.mouse_down(btn)
            self.send_json(200, {"ok": True})
            return
        if action == "up":
            btn = str(payload.get("button", "left")).lower()
            InputController.mouse_up(btn)
            self.send_json(200, {"ok": True})
            return
        if action == "scroll":
            dy = as_int(payload.get("dy", 0), 0, -500, 500)
            InputController.mouse_scroll(dy)
            self.send_json(200, {"ok": True})
            return
        # "moveto" is the historical spelling; keep both accepted.
        if action in ("move_to", "moveto"):
            x = as_int(payload.get("x", 0), 0, 0, 10000)
            y = as_int(payload.get("y", 0), 0, 0, 10000)
            InputController.mouse_move_to(x, y)
            self.send_json(200, {"ok": True})
            return
        raise ApiError(400, f"Unknown mouse action: {action}")

    def _input_keyboard(self, payload: Dict[str, Any]):
        text = payload.get("text")
        key = payload.get("key")
        hotkey = payload.get("hotkey")
        # The web UI (mobile.html / client_web) sends {action:'hotkey', keys:[...]};
        # accept that shape as an alias of the native {hotkey:[...]} contract.
        if hotkey is None and isinstance(payload.get("keys"), list):
            hotkey = payload.get("keys")

        if text is not None:
            if not isinstance(text, str) or len(text) > 10000:
                raise ApiError(400, "Invalid text payload")
            InputController.type_text(text)
            self.send_json(200, {"ok": True})
            return
        if key is not None:
            key_str = str(key)
            if not key_str or len(key_str) > 32:
                raise ApiError(400, "Invalid key")
            ok = InputController.key_press(key_str)
            self.send_json(200, {"ok": ok})
            return
        if hotkey is not None:
            if (
                not isinstance(hotkey, list)
                or not hotkey
                or len(hotkey) > 6
                or not all(isinstance(k, str) and 0 < len(k) <= 32 for k in hotkey)
            ):
                raise ApiError(400, "Invalid hotkey combination")
            ok = InputController.hotkey(*hotkey)
            self.send_json(200, {"ok": ok})
            return
        raise ApiError(400, "Missing text, key, or hotkey parameter")

    def _media_control(self, payload: Dict[str, Any]):
        action = str(payload.get("action", "")).strip().lower()
        percent = payload.get("percent")

        if action == "set_volume" and percent is not None:
            pct = as_int(percent, 50, 0, 100)
            ok = InputController.set_volume_percent(pct)
            self.send_json(200, {"ok": ok, "volume": pct})
            return
        if action == "get_volume":
            vol = InputController.get_volume_percent()
            self.send_json(200, {"ok": True, "volume": vol if vol is not None else 50})
            return
        if action == "set_brightness" and percent is not None:
            pct = as_int(percent, 70, 0, 100)
            ok = InputController.set_brightness_percent(pct)
            self.send_json(200, {"ok": ok, "brightness": pct})
            return
        if action == "volume_up":
            InputController.volume_up()
            self.send_json(200, {"ok": True})
            return
        if action == "volume_down":
            InputController.volume_down()
            self.send_json(200, {"ok": True})
            return
        if action in ("volume_mute", "mute"):
            InputController.volume_mute()
            self.send_json(200, {"ok": True})
            return
        if action in ("play", "pause", "play_pause"):
            InputController.media_play_pause()
            self.send_json(200, {"ok": True})
            return
        if action == "next":
            InputController.media_next()
            self.send_json(200, {"ok": True})
            return
        if action in ("prev", "previous"):
            InputController.media_prev()
            self.send_json(200, {"ok": True})
            return
        if action == "stop":
            InputController.media_stop()
            self.send_json(200, {"ok": True})
            return

        raise ApiError(400, f"Unknown media action: {action}")

