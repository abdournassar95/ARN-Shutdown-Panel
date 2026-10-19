# Changelog

## [2.0.1] — 2026-10-19

### 🔒 Security
- **Lock-screen bypass removed**: `unlock_screen()` accepted the literal `admin`
  in addition to the configured password (`gui/api.py`).
- **No predictable default LAN password**: a random password is generated on
  first run (the server is still disabled until explicitly started).
- **LAN password is hashed** with PBKDF2-HMAC-SHA256 (240k iterations, random
  salt) in `core/security.py`; the legacy plain-text `remotePassword` key is
  migrated automatically and never written again. `settings.json` is chmod 600.
- **Token rotation now revokes everything**: `rotate_token()` and any credential
  change discard all sessions and issue a fresh master token. Previously old
  tokens stayed valid forever.
- **XSS fixed** in the mobile/file-manager and client UIs: remote file names,
  paths, client IPs and user agents are rendered with `textContent` instead of
  `innerHTML`; discovery payloads are escaped.
- **Path traversal blocked** on `/fonts/` and the HTTPS private key is written
  with `0600` permissions.
- Passwords are no longer pre-filled in the UI (`index.html`, client login) and
  the fields are masked.

### 🐞 Functional fixes
- **Schedules: `display_off` no longer becomes a full shutdown.** It was missing
  from `VALID_ACTIONS`, so the sanitiser silently rewrote it to `shutdown`.
- **`hibernate` implemented** for Windows (`shutdown /h`), Linux
  (`systemctl hibernate`) and macOS.
- **Keyboard hotkeys from the web UI work**: `{action:"hotkey", keys:[...]}` is
  accepted; payload limits restored.
- **Remote pause/resume now controls the countdown** instead of failing as an
  unknown power action; `/api/abort` reports success on platforms without a
  native abort command.
- **Touch-to-click moves the pointer first** using `/api/screen/size`; previously
  it clicked wherever the host cursor happened to be.
- `SW_SHOW`/`SW_HIDE` and `KEYEVENTF_KEYUP` are defined on every platform,
  eliminating two `NameError`s (taskbar toggle and key press returned HTTP 500).
- `subprocess` is imported in `remote_server` (opening a file from the phone
  returned HTTP 500).
- Removed three duplicated, dead handler definitions in `RemoteServer`.
- The frameless main window is draggable again (pywebview drag region on the
  brand bar; `easy_drag` is EdgeChromium-only).

### 🌍 UI / i18n
- Restored the missing token panel (`remoteTokenVal`, copy/rotate) and the
  “cancel countdown” button referenced by `app.js` but absent from `index.html`.
- Mobile UI now applies `data-i18n` translations and gained the 21 missing keys;
  the client UI gained its 15 missing keys (including `lockPlaceholder`).
- Added the missing Cairo Latin font subsets.

### 📦 Build
- Added the missing `ShutdownPanel.spec` and `ShutdownPanelClient.spec`
  (they were excluded by `*.spec` in `.gitignore`) plus `assets/icon.ico`.
- `build_exe.py` fails with a clear message when a spec is missing.
- Version bumped to 2.0.1; docs corrected (PyQt6 badge, MIT claim, test counts).

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
- README rewritten, proprietary ARN Technology LICENSE added, tests expanded (24 tests).

### 📦 Packaging
- `build_exe.py` fixed (PyInstaller detection actually works; portable `--add-data`;
  auto-generated icon; dev modules excluded).
- Dependencies split into `requirements.txt` / `requirements-dev.txt`.

## [1.0.0] — initial release
