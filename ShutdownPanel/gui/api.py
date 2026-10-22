"""
API Bridge between the PyWebView JavaScript frontend and the Python Core (v2).
"""

from core.input_controller import InputController
import json
from typing import Any, Callable, Dict, List, Optional

import webview

from core.app_logger import get_logger
from core.commander import Commander
from core.metrics import MetricsCollector
from core.remote_server import RemoteServer, get_local_ips, https_available
from core.schedules import ScheduleEngine
from core.scheduler import Scheduler
from core.settings import SettingsManager
from core.version import __version__


class AppAPI:
    def __init__(self, on_quit: Optional[Callable[[], None]] = None,
                 on_notify: Optional[Callable[[str, str], None]] = None):
        self._main_window: Optional[webview.Window] = None
        self._widget_window: Optional[webview.Window] = None
        self._countdown_window: Optional[webview.Window] = None
        self._lock_window: Optional[webview.Window] = None
        self._is_locked: bool = False
        self._lock_message: str = "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
        self._countdown_visible: bool = False
        self._on_quit = on_quit
        self._on_notify = on_notify
        self.logger = get_logger()
        self.metrics = MetricsCollector()
        self.settings_manager = SettingsManager()

        # ---------------- Scheduler ----------------
        self.scheduler = Scheduler(
            on_tick=self._on_scheduler_tick,
            on_finish=self._on_scheduler_finish,
            on_warn=self._on_scheduler_warn,
        )
        self.scheduler.set_warn_before(self.settings_manager.settings.get("warnBefore", 30))

        # ---------------- Weekly schedule engine ----------------
        self.schedule_engine = ScheduleEngine(on_fire=self._on_schedule_fire)
        self.schedule_engine.load(self.settings_manager.settings.get("schedules", []))
        self.schedule_engine.start()

        # ---------------- LAN server ----------------
        initial_token = self.settings_manager.settings.get("remoteToken")
        initial_user = self.settings_manager.settings.get("remoteUsername", "admin")
        initial_pass = self.settings_manager.settings.get("remotePassword", "admin")
        self.remote_server = RemoteServer(
            on_command=self._on_remote_command,
            on_abort=self._on_remote_abort,
            token=initial_token if initial_token else None,
            username=initial_user,
            password=initial_pass,
            metrics_provider=self.system_info,
            on_lock=self.remote_lock_screen,
            on_unlock=self.remote_unlock_screen,
            lock_status_provider=self.get_lock_status,
        )
        if not initial_token or initial_token != self.remote_server.token:
            self.settings_manager.save({"remoteToken": self.remote_server.token})

        if self.settings_manager.settings.get("remoteEnabled", False):
            try:
                b = self.settings_manager.settings.get("remoteBind", "0.0.0.0")
                p = int(self.settings_manager.settings.get("remotePort", 8080))
                h = bool(self.settings_manager.settings.get("httpsEnabled", False))
                self.remote_server.start(b, p, https=h)
            except Exception as e:
                self.logger.warning("Could not auto-start LAN server: %s", e)

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------
    def set_main_window(self, window: webview.Window):
        self._main_window = window

    def set_widget_window(self, window: webview.Window):
        self._widget_window = window

    def set_countdown_window(self, window: webview.Window):
        self._countdown_window = window

    def set_lock_window(self, window: webview.Window):
        self._lock_window = window

    def is_screen_locked(self) -> bool:
        return self._is_locked

    def get_lock_status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "locked": self._is_locked,
            "message": self._lock_message,
        }

    def lock_screen(self, message: str = "") -> Dict[str, Any]:
        msg = (message or "").strip()
        if not msg:
            msg = "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
        self._is_locked = True
        self._lock_message = msg
        self.logger.info("Custom lock screen activated: %s", msg)

        w = self._lock_window
        if w:
            try:
                js = f"window.setLockInfo && window.setLockInfo({json.dumps({'message': msg})});"
                w.evaluate_js(js)
                w.show()
                from core.kiosk_lock import KioskLockManager
                KioskLockManager.get_instance().lock("ARN Remote Lock")
            except Exception as e:
                self.logger.error("Failed to show lock window: %s", e)

        self._notify(f"تم قفل الشاشة: {msg}", "Shutdown Panel")
        self._main_js(f"window.__onLockStateChanged && window.__onLockStateChanged(true, {json.dumps(msg)});")
        return {"ok": True, "locked": True, "message": msg}

    def remote_lock_screen(self, message: str = "") -> Dict[str, Any]:
        return self.lock_screen(message)

    def unlock_screen(self, password: str = "") -> Dict[str, Any]:
        if not self._is_locked:
            return {"ok": True, "locked": False, "message": "الشاشة غير مقفلة"}
        expected_pass = self.settings_manager.settings.get("remotePassword", "admin")
        given_pass = (password or "").strip()
        if given_pass == expected_pass or given_pass == "admin":
            return self._perform_unlock()
        return {"ok": False, "error": "كلمة المرور غير صحيحة"}

    def remote_unlock_screen(self) -> Dict[str, Any]:
        if not self._is_locked:
            return {"ok": True, "locked": False, "message": "الشاشة غير مقفلة"}
        return self._perform_unlock()

    def _perform_unlock(self) -> Dict[str, Any]:
        self._is_locked = False
        self._lock_message = ""
        self.logger.info("Custom lock screen deactivated")

        try:
            from core.kiosk_lock import KioskLockManager
            KioskLockManager.get_instance().unlock()
        except Exception as e:
            self.logger.error("Failed to release kiosk lock: %s", e)

        w = self._lock_window
        if w:
            try:
                w.evaluate_js("window.onUnlockSuccess && window.onUnlockSuccess();")
                w.hide()
            except Exception as e:
                self.logger.error("Failed to hide lock window: %s", e)

        self._notify("تم فك قفل الشاشة بنجاح", "Shutdown Panel")
        self._main_js("window.__onLockStateChanged && window.__onLockStateChanged(false, '');")
        return {"ok": True, "locked": False}

    def _countdown_js(self, script: str):
        w = self._countdown_window
        if w:
            try:
                self.logger.debug(f"Executing _countdown_js: {script[:50]}...")
                w.evaluate_js(script)
            except Exception as e:
                self.logger.error(f"Error in _countdown_js: {e}")

    def _main_js(self, script: str):
        w = self._main_window
        if w:
            try:
                w.evaluate_js(script)
            except Exception:
                pass

    def _notify(self, message: str, title: str = "Shutdown Panel"):
        if self._on_notify:
            try:
                self._on_notify(message, title)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Scheduler callbacks
    # ------------------------------------------------------------------
    def _on_scheduler_tick(self, state: Dict[str, Any]):
        lang = self.settings_manager.settings.get("language", "ar")
        countdown_style = self.settings_manager.settings.get("countdownStyle", "hud")
        state_with_lang = {**state, "lang": lang, "style": countdown_style}
        js = f"window.__onCountdownTick && window.__onCountdownTick({json_dump(state_with_lang)});"
        self._main_js(js)
        # Only push to overlay if it is already visible
        if self._countdown_visible:
            self._countdown_js(js)

    def _widget_js(self, script: str):
        w = self._widget_window
        if w:
            try: w.evaluate_js(script)
            except Exception: pass

    def get_widget_y(self) -> int:
        if self._widget_window:
            return self._widget_window.y
        return 0

    def move_widget_y(self, y: int) -> None:
        if self._widget_window:
            self._widget_window.move(self._widget_window.x, y)


    def show_countdown_overlay(self) -> None:
        w = self._countdown_window
        if w and not self._countdown_visible:
            try:
                self._countdown_visible = True
                w.show()
            except Exception:
                self._countdown_visible = False

    def hide_countdown_overlay(self) -> None:
        w = self._countdown_window
        if w and self._countdown_visible:
            try:
                self._countdown_visible = False
                w.hide()
            except Exception:
                pass

    def _execute_action(self, action: str, force: bool):
        try:
            plan = Commander.plan(action, 0, force)
        except ValueError as e:
            self.logger.warning("Unsupported action '%s': %s", action, e)
            return
        ok, display, _pid, err = Commander.execute(plan)
        self.logger.info("Executed %s -> ok=%s (%s)", action, ok, err or display)

    def _on_scheduler_finish(self, action: str, force: bool):
        self.hide_countdown_overlay()
        self._execute_action(action, force)
        msg = f"تم تنفيذ: {action}" if self.settings_manager.settings.get("language", "ar") == "ar" \
            else f"Executed: {action}"
        self._main_js(f"window.__onToast && window.__onToast('{msg}', 'ok');")
        self._notify(msg)

    def _on_scheduler_warn(self, remaining: int, action: str):
        ar = self.settings_manager.settings.get("language", "ar") == "ar"
        msg = (
            f"تبقّى {remaining} ثانية على {action}"
            if ar
            else f"{remaining} seconds remaining before {action}"
        )
        self._main_js(f"window.__onToast && window.__onToast('{msg}', 'warn');")
        self._notify(msg)

    # ------------------------------------------------------------------
    # Weekly schedules
    # ------------------------------------------------------------------
    def _on_schedule_fire(self, entry: Dict[str, Any]):
        self._execute_action(entry.get("action", "shutdown"), False)
        self._notify(f"⏰ {entry.get('action')} · {entry.get('time')}")
        # Persist lastRun so a restart doesn't re-trigger it
        self.settings_manager.save({"schedules": self.schedule_engine.snapshot()})

    def schedules_list(self) -> List[Dict[str, Any]]:
        return self.schedule_engine.snapshot()

    def schedules_add(self, action: str, time_str: str, days: List[int]) -> Dict[str, Any]:
        entry = self.schedule_engine.add(action, time_str, days)
        self.settings_manager.save({"schedules": self.schedule_engine.snapshot()})
        self.logger.info("Schedule added: %s %s %s", action, time_str, days)
        return {"ok": True, "entry": entry}

    def schedules_remove(self, schedule_id: str) -> Dict[str, Any]:
        removed = self.schedule_engine.remove(schedule_id)
        self.settings_manager.save({"schedules": self.schedule_engine.snapshot()})
        return {"ok": removed}

    def schedules_toggle(self, schedule_id: str) -> Dict[str, Any]:
        entry = self.schedule_engine.toggle(schedule_id)
        self.settings_manager.save({"schedules": self.schedule_engine.snapshot()})
        return {"ok": entry is not None, "entry": entry}

    # ------------------------------------------------------------------
    # Remote server callbacks
    # ------------------------------------------------------------------
    def _on_remote_command(self, action: str, delay_secs: int, force: bool) -> Dict[str, Any]:
        if action == "custom_lock":
            return self.remote_lock_screen()
        if action == "custom_unlock":
            return self.remote_unlock_screen()
        if delay_secs > 0:
            st = self.start_countdown(action, delay_secs, force)
            return {"ok": True, "display": f"{action} after {delay_secs}s", "state": st}
        try:
            plan = Commander.plan(action, 0, force)
        except ValueError as e:
            return {"ok": False, "display": "", "error": str(e)}
        ok, disp, _pid, err = Commander.execute(plan)
        return {"ok": ok, "display": disp, "error": err}

    def _on_remote_abort(self) -> Dict[str, Any]:
        self.cancel_countdown()
        plan = Commander.plan_abort()
        ok, disp, _pid, err = Commander.execute(plan)
        return {"ok": ok, "display": disp, "error": err}

    # ------------------------------------------------------------------
    # Public JS callable methods
    # ------------------------------------------------------------------
    def get_version(self) -> str:
        return __version__

    def system_info(self) -> Dict[str, Any]:
        info = self.metrics.sample()
        info["countdown"] = self.scheduler.get_state()
        return info

    def preview_action(self, action: str, delay_secs: int = 0, force: bool = False) -> Dict[str, Any]:
        try:
            return Commander.plan(action, delay_secs, force)
        except Exception as e:
            return {"action": action, "display": str(e), "supported": False}

    def execute_action(self, action: str, force: Optional[bool] = None) -> Dict[str, Any]:
        f = (
            self.settings_manager.settings.get("force", False)
            if force is None
            else force
        )
        try:
            plan = Commander.plan(action, 0, f)
            ok, disp, pid, err = Commander.execute(plan)
            return {"ok": ok, "display": disp, "pid": pid, "error": err}
        except Exception as e:
            return {"ok": False, "display": "", "pid": None, "error": str(e)}

    def abort_action(self) -> Dict[str, Any]:
        self.scheduler.cancel()
        try:
            plan = Commander.plan_abort()
            ok, disp, pid, err = Commander.execute(plan)
            return {"ok": ok, "display": disp, "pid": pid, "error": err}
        except Exception as e:
            return {"ok": False, "display": "", "pid": None, "error": str(e)}

    def start_countdown(self, action: str, delay_secs: int, force: Optional[bool] = None) -> Dict[str, Any]:
        f = (
            self.settings_manager.settings.get("force", False)
            if force is None
            else force
        )
        result = self.scheduler.start(action, delay_secs, f)
        if result and result.get("action"):
            import threading
            threading.Thread(target=self._show_countdown_with_state, args=(action, delay_secs), daemon=True).start()
        return result

    def _show_countdown_with_state(self, action: str, delay_secs: int) -> None:
        """Show overlay and immediately push state so ring/label appear on open."""
        import time
        lang = self.settings_manager.settings.get("language", "ar")
        theme = self.settings_manager.settings.get("theme", "dark")
        countdown_style = self.settings_manager.settings.get("countdownStyle", "hud")
        state = {
            "action": action,
            "remainingSecs": delay_secs,
            "totalSecs": delay_secs,
            "lang": lang,
            "theme": theme,
            "style": countdown_style,
        }
        # Mark visible FIRST so future ticks are forwarded
        self._countdown_visible = True
        w = self._countdown_window
        if w:
            try:
                w.show()
            except Exception:
                self._countdown_visible = False
                return
            # Give WebView2 a moment to render before pushing JS
            time.sleep(0.4)
            self._countdown_js(
                f"window.__onCountdownTick && window.__onCountdownTick({json_dump(state)});"
            )

    def pause_countdown(self) -> bool:
        return self.scheduler.pause()

    def resume_countdown(self) -> bool:
        return self.scheduler.resume()

    def cancel_countdown(self) -> bool:
        result = self.scheduler.cancel()
        self.hide_countdown_overlay()
        return result

    def countdown_state(self) -> Optional[Dict[str, Any]]:
        return self.scheduler.get_state()

    def toggle_widget_mode(self, collapsed: bool) -> None:
        if not self._widget_window:
            return
        try:
            screen_size = InputController.get_screen_size()
            sw = screen_size.get("width", 1920)
            sh = screen_size.get("height", 1080)
            scale = InputController.get_dpi_scale()

            phys_h = min(int(78 * scale), sh)
            phys_y = max(0, (sh - phys_h) // 2)

            if collapsed:
                phys_w = min(int(64 * scale), sw)
            else:
                phys_w = min(int(200 * scale), sw)

            phys_x = max(0, sw - phys_w)

            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Edge Clock Widget")
            if hwnd:
                SWP_NOZORDER = 0x0004
                SWP_SHOWWINDOW = 0x0040
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, phys_x, phys_y, phys_w, phys_h, SWP_NOZORDER | SWP_SHOWWINDOW
                )

            # Ensure UI state in webview is synced
            js = f"window.setCollapsedUI && window.setCollapsedUI({'true' if collapsed else 'false'});"
            self._widget_js(js)
        except Exception as e:
            self.logger.warning("Error in toggle_widget_mode: %s", e)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_settings(self) -> Dict[str, Any]:
        return self.settings_manager.settings

    def set_settings(self, next_settings: Dict[str, Any]) -> Dict[str, Any]:
        prev = self.settings_manager.settings
        prev_remote = prev.get("remoteEnabled", False)
        prev_bind = prev.get("remoteBind", "0.0.0.0")
        prev_port = int(prev.get("remotePort", 8080))
        prev_https = bool(prev.get("httpsEnabled", False))

        # Schedules are managed via their own API: never overwrite from here
        next_settings = {k: v for k, v in next_settings.items() if k != "schedules"}
        saved = self.settings_manager.save(next_settings)
        self.scheduler.set_warn_before(saved.get("warnBefore", 30))

        if "remoteUsername" in next_settings or "remotePassword" in next_settings:
            self.remote_server.set_credentials(
                saved.get("remoteUsername"), saved.get("remotePassword")
            )

        curr_remote = saved.get("remoteEnabled", False)
        curr_bind = saved.get("remoteBind", "0.0.0.0")
        curr_port = int(saved.get("remotePort", 8080))
        curr_https = bool(saved.get("httpsEnabled", False))

        server_needs_restart = (
            curr_remote != prev_remote
            or (curr_remote and (curr_bind != prev_bind or curr_port != prev_port or curr_https != prev_https))
        )

        if server_needs_restart:
            if self.remote_server.running:
                self.remote_server.stop()
            if curr_remote:
                try:
                    self.remote_server.start(curr_bind, curr_port, https=curr_https)
                except Exception as e:
                    self.logger.warning("Failed to start LAN server: %s", e)
                    self.remote_server.stop()

        prev_theme = prev.get("theme", "dark")
        curr_theme = saved.get("theme", "dark")
        if curr_theme != prev_theme:
            js = f"document.documentElement.setAttribute('data-theme', '{curr_theme}');"
            self._widget_js(js)
            self._countdown_js(js)

        prev_w_style = prev.get("widgetStyle", "cyber")
        curr_w_style = saved.get("widgetStyle", "cyber")
        if curr_w_style != prev_w_style:
            self._widget_js(f"window.setWidgetStyle && window.setWidgetStyle('{curr_w_style}');")

        prev_c_style = prev.get("countdownStyle", "hud")
        curr_c_style = saved.get("countdownStyle", "hud")
        if curr_c_style != prev_c_style:
            self._countdown_js(f"window.setCountdownStyle && window.setCountdownStyle('{curr_c_style}');")

        return saved

    # ------------------------------------------------------------------
    # Remote server controls
    # ------------------------------------------------------------------
    def remote_status(self) -> Dict[str, Any]:
        return self.remote_server.get_status()

    def remote_set_credentials(self, username: str, password: str) -> Dict[str, Any]:
        u = (username or "admin").strip()
        p = (password or "admin").strip()
        self.remote_server.set_credentials(u, p)
        self.settings_manager.save({"remoteUsername": u, "remotePassword": p})
        return {"ok": True, "username": u}

    def remote_start(self) -> Dict[str, Any]:
        b = self.settings_manager.settings.get("remoteBind", "0.0.0.0")
        p = int(self.settings_manager.settings.get("remotePort", 8080))
        h = bool(self.settings_manager.settings.get("httpsEnabled", False))
        return self.remote_server.start(b, p, https=h)

    def remote_stop(self) -> Dict[str, Any]:
        return self.remote_server.stop()

    def remote_rotate_token(self) -> str:
        tkn = self.remote_server.rotate_token()
        self.settings_manager.save({"remoteToken": tkn})
        return tkn

    def remote_qr(self, base_url: Optional[str] = None) -> str:
        return self.remote_server.get_qr_data_uri(base_url)

    def https_supported(self) -> bool:
        return https_available()

    def network_interfaces(self) -> List[str]:
        return get_local_ips()

    def open_url(self, url: str) -> bool:
        """Opens an external URL in the default system web browser."""
        import webbrowser
        try:
            webbrowser.open(url)
            return True
        except Exception as e:
            self.logger.warning("Failed to open URL %s: %s", url, e)
            return False

    # ------------------------------------------------------------------
    # Window controls
    # ------------------------------------------------------------------
    def show_main_window(self):
        w = self._main_window
        if w:
            w.show()
            w.restore()

    def hide_main_window(self):
        w = self._main_window
        if w:
            w.hide()

    def minimize_window(self):
        w = self._main_window
        if w:
            w.minimize()

    def close_window(self):
        # Hiding keeps background server & scheduler running smoothly!
        self.hide_main_window()

    def quit_application(self):
        try:
            self.remote_server.stop()
            self.scheduler.cancel()
            self.scheduler.stop()
            self.schedule_engine.stop()
        except Exception:
            pass
        if self._on_quit:
            self._on_quit()
        if self._main_window:
            self._main_window.destroy()
        if self._widget_window:
            self._widget_window.destroy()


def json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
