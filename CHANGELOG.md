# Changelog

## [2.0.0] — 2026-08-30

### 🐞 Critical fixes
- **Scheduler crash fixed**: `UnboundLocalError` on `act` in the warn path killed the
  countdown thread — scheduled shutdowns never fired when a warning was configured
  (the default). The scheduler now uses a single persistent worker thread.
- **File upload fixed**: replaced the removed `cgi` module (Python 3.13+) with a
  custom streaming multipart parser (size-limited, disk-streamed).
- **Security: `/api/qr` is now authenticated** — it embeds the access token and was
  previously public (full auth bypass for anyone on the LAN).
- **Security: CORS `*` removed** — the API is same-origin only.
- **x64 `SendInput` struct fixed**: the INPUT union was missing MOUSEINPUT, making
  `sizeof(INPUT)` wrong on 64-bit — Arabic/Unicode typing never worked.

### 🆕 New features
- Weekly schedule engine (e.g. shut down daily at 23:00) with a full desktop UI tab.
- Mobile remote: process manager (list/kill), Wake-on-LAN, clipboard sync,
  file rename, new-folder creation, live CPU/RAM/disk/battery/uptime chips.
- Mobile UI is now bilingual (AR/EN) with RTL/LTR switching.
- PWA support: installable on the phone home screen (manifest + icon).
- Optional HTTPS with an auto-generated self-signed certificate (cryptography).
- Windows toast notifications for countdown warnings and schedule fires.
- Battery status (desktop header + mobile), disk usage metric.
- DPI awareness: correct window/widget placement on 125%/150% scaled screens.
- Single-instance protection; auto-start with Windows setting.

### 🔧 Improvements
- Black-screen startup fixed: windows are hidden until the page loads, and the
  Google Fonts CDN dependency was replaced with bundled local WOFF2 fonts.
- Edge widget redesigned: 24h clock + seconds, cleaner dial, countdown alert state.
- Exact volume control via the Windows audio COM API (no more 100 key presses).
- `Commander.execute` now verifies exit codes and captures stderr (no pipe deadlock).
- Safe delete: files go to the Recycle Bin (send2trash); system paths are protected.
- Folder ZIP download streams from a temp file (no more RAM blow-up, 2 GB cap).
- QR code generation cached (was regenerated every 3 s while polling).
- Screen capture via `mss` (3-5× faster) with a Pillow fallback.
- Text typing batched into a single SendInput call.
- Rate limiting now covers GET requests too, with idle-IP cleanup.
- Input validation on every endpoint (proper 400 JSON instead of dropped connections).
- Rotating file logging (`logs/app.log`) replaces print statements.
- Settings are saved atomically; changing port/bind/HTTPS restarts the server.
- README rewritten, LICENSE (MIT) added, tests expanded (24 tests).

### 📦 Packaging
- `build_exe.py` fixed (PyInstaller detection actually works; portable `--add-data`;
  auto-generated icon; dev modules excluded).
- Dependencies split into `requirements.txt` / `requirements-dev.txt`.

## [1.0.0] — initial release
