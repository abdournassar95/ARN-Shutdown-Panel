"""
Shutdown Panel — Desktop (Python Edition) — v2
Main entry point: DPI-aware centered main window, right-edge clock widget,
system tray with notifications, and single-instance protection.
"""

import pathlib
import socket
import sys
import threading
from typing import Optional

import pystray
import webview
from PIL import Image, ImageDraw

from core.app_logger import get_logger
from core.input_controller import InputController, enable_dpi_awareness
from core.version import __version__

try:
    from gui.api import AppAPI
except Exception as e:  # pragma: no cover
    get_logger().critical("Failed to import AppAPI: %s", e)
    raise

SINGLE_INSTANCE_PORT = 57913
tray_icon: Optional[pystray.Icon] = None
_tray_holder: dict = {"icon": None}


def get_web_dir() -> pathlib.Path:
    # When running from a PyInstaller --onefile bundle, assets are in sys._MEIPASS
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return pathlib.Path(base) / "gui" / "web"
    return pathlib.Path(__file__).resolve().parent / "gui" / "web"


def acquire_single_instance() -> Optional[socket.socket]:
    """Prevents multiple app instances (tray duplicates / port conflicts)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def create_tray_image():
    """Generates a high-res glowing cyan power icon for the system tray."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(12, 20, 36, 255), outline=(34, 211, 238, 255), width=3)
    draw.arc((14, 14, 50, 50), start=300, end=240, fill=(34, 211, 238, 255), width=4)
    draw.line((32, 10, 32, 30), fill=(34, 211, 238, 255), width=4)
    return img


def desktop_notify(message: str, title: str = "Shutdown Panel"):
    """Shows a Windows notification through the tray icon (best effort)."""
    icon = _tray_holder.get("icon")
    if icon is None:
        return
    try:
        icon.notify(message, title)
    except Exception:
        pass


def setup_tray(api: AppAPI):
    global tray_icon

    def show_app(icon, item):
        api.show_main_window()

    def do_sleep(icon, item):
        api.execute_action("sleep")

    def do_shutdown(icon, item):
        api.execute_action("shutdown")

    def quit_app(icon, item):
        def exit_worker():
            try:
                icon.stop()
            except Exception:
                pass
            api.quit_application()
            import os

            os._exit(0)

        threading.Thread(target=exit_worker, daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem(f"🖥️ فتح لوحة التحكم — v{__version__}", show_app, default=True),
        pystray.MenuItem("🌙 وضع النوم", do_sleep),
        pystray.MenuItem("🛑 إيقاف التشغيل", do_shutdown),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ خروج نهائي", quit_app),
    )

    tray_icon = pystray.Icon(
        "ShutdownPanel", create_tray_image(), f"Shutdown Panel v{__version__}", menu
    )
    _tray_holder["icon"] = tray_icon
    threading.Thread(target=tray_icon.run, daemon=True, name="TrayThread").start()


def main():
    logger = get_logger()
    logger.info("Starting Shutdown Panel v%s", __version__)

    # DPI awareness MUST be enabled before any window is created
    enable_dpi_awareness()

    instance_lock = acquire_single_instance()
    if instance_lock is None:
        logger.warning("Another instance is already running — exiting.")
        print("Shutdown Panel is already running (check the system tray).")
        return

    def on_quit_requested():
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass

    api = AppAPI(on_quit=on_quit_requested, on_notify=desktop_notify)

    web_dir = get_web_dir()
    index_uri = (web_dir / "index.html").as_uri()
    widget_uri = (web_dir / "widget.html").as_uri()
    countdown_uri = (web_dir / "countdown_overlay.html").as_uri()
    lock_uri = (web_dir / "lock_screen.html").as_uri()

    # Physical screen metrics (correct after DPI awareness)
    screen_size = InputController.get_screen_size()
    sw = screen_size.get("width", 1920)
    sh = screen_size.get("height", 1080)
    scale = InputController.get_dpi_scale()

    # ---------------------------------------------------------- Main window
    main_w = min(int(780 * scale), sw - 40)
    main_h = min(int(740 * scale), sh - 40)
    main_x = max(0, (sw - main_w) // 2)
    main_y = max(0, (sh - main_h) // 2)

    main_window = webview.create_window(
        title=f"Shutdown Panel v{__version__}",
        url=index_uri,
        js_api=api,
        width=main_w,
        height=main_h,
        x=main_x,
        y=main_y,
        resizable=False,
        frameless=True,
        easy_drag=False,
        hidden=True,
        background_color="#070c16",
    )
    api.set_main_window(main_window)

    # Close button hides to tray; the app keeps running in the background
    def on_main_closing():
        main_window.hide()
        return False

    main_window.events.closing += on_main_closing

    # ---------------------------------------------------------- Edge widget
    widget_w = min(int(200 * scale), sw)
    widget_h = min(int(78 * scale), sh)
    widget_x = max(0, sw - widget_w)
    widget_y = max(0, (sh - widget_h) // 2)

    widget_window = webview.create_window(
        title="Edge Clock Widget",
        url=widget_uri,
        js_api=api,
        width=widget_w,
        height=widget_h,
        x=widget_x,
        y=widget_y,
        resizable=False,
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
        background_color="#070c16",
    )
    api.set_widget_window(widget_window)

    def on_widget_shown():
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Edge Clock Widget")
            if hwnd:
                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_APPWINDOW = 0x00040000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    widget_window.events.shown += on_widget_shown

    # ------------------------------------------------ Countdown overlay window
    countdown_w = 320
    countdown_h = 72
    countdown_x = max(0, (sw - countdown_w) // 2)
    countdown_y = 0

    countdown_window = webview.create_window(
        title="Countdown Overlay",
        url=countdown_uri,
        js_api=api,
        width=countdown_w,
        height=countdown_h,
        x=countdown_x,
        y=countdown_y,
        resizable=False,
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
        background_color="#070c16",
    )
    api.set_countdown_window(countdown_window)

    def on_countdown_shown():
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Countdown Overlay")
            if hwnd:
                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_APPWINDOW = 0x00040000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    countdown_window.events.shown += on_countdown_shown

    # ------------------------------------------------ Custom Remote Lock Screen
    lock_window = webview.create_window(
        title="ARN Remote Lock",
        url=lock_uri,
        js_api=api,
        width=sw,
        height=sh,
        x=0,
        y=0,
        resizable=False,
        frameless=True,
        easy_drag=False,
        fullscreen=True,
        on_top=True,
        hidden=True,
        background_color="#050811",
    )
    api.set_lock_window(lock_window)

    def on_lock_closing():
        if api.is_screen_locked():
            return False
        return True

    lock_window.events.closing += on_lock_closing

    # Ensure taskbar is visible at launch
    try:
        from core.kiosk_lock import KioskLockManager
        KioskLockManager.get_instance()._set_taskbars_visible(True)
    except Exception:
        pass

    # Show windows only after their pages finished loading (kills the black
    # screen), with a safety timer in case the loaded event never fires.
    def reveal(window, delay: float = 0.0):
        try:
            if delay:
                import time
                time.sleep(delay)
            window.show()
        except Exception:
            pass

    def force_hide(window):
        """Ensure a window stays hidden (transparent windows may flash on load)."""
        try:
            window.hide()
        except Exception:
            pass

    start_minimized = bool(api.settings_manager.settings.get("startMinimized", True))

    if start_minimized:
        main_window.events.loaded += lambda: force_hide(main_window)
    else:
        main_window.events.loaded += lambda: reveal(main_window)

    widget_window.events.loaded += lambda: reveal(widget_window)
    # Countdown overlay: hide immediately after load; show only when a countdown starts
    countdown_window.events.loaded += lambda: force_hide(countdown_window)
    # Lock screen: hide immediately after load; show only when activated
    lock_window.events.loaded += lambda: force_hide(lock_window)
    threading.Timer(7.0, reveal, args=(widget_window,)).start()

    # ---------------------------------------------------------- Tray + run
    setup_tray(api)

    try:
        webview.start(debug=False)
    finally:
        try:
            from core.kiosk_lock import KioskLockManager
            KioskLockManager.get_instance().unlock()
        except Exception:
            pass
        try:
            api.quit_application()
        except Exception:
            pass
        if instance_lock:
            try:
                instance_lock.close()
            except Exception:
                pass
        logger.info("Shutdown Panel exited")


if __name__ == "__main__":
    main()
