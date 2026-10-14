"""
Shutdown Panel — Desktop Client
Entry point for the remote control client application.
Connects to a Shutdown Panel server on the LAN to control it.
"""

import pathlib
import socket
import sys
import threading
from typing import Optional

import webview

from core.app_logger import get_logger
from core.input_controller import enable_dpi_awareness, InputController


def get_client_web_dir() -> pathlib.Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return pathlib.Path(base) / "gui" / "client_web"
    return pathlib.Path(__file__).resolve().parent / "gui" / "client_web"


SINGLE_INSTANCE_PORT = 57914  # Different from server's port


def acquire_single_instance() -> Optional[socket.socket]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def main():
    logger = get_logger()
    logger.info("Starting Shutdown Panel Client")

    enable_dpi_awareness()

    instance_lock = acquire_single_instance()
    if instance_lock is None:
        logger.warning("Client is already running — exiting.")
        print("Shutdown Panel Client is already running.")
        return

    from gui.client_api import ClientAPI
    api = ClientAPI()

    web_dir = get_client_web_dir()
    index_uri = (web_dir / "index.html").as_uri()

    screen_size = InputController.get_screen_size()
    sw = screen_size.get("width", 1920)
    sh = screen_size.get("height", 1080)
    scale = InputController.get_dpi_scale()

    win_w = 950
    win_h = 650
    win_x = max(0, (sw - win_w) // 2)
    win_y = max(0, (sh - win_h) // 2)

    window = webview.create_window(
        title="Shutdown Panel — Client",
        url=index_uri,
        js_api=api,
        width=win_w,
        height=win_h,
        x=win_x,
        y=win_y,
        resizable=True,
        frameless=True,
        min_size=(600, 500),
        easy_drag=False,
        hidden=True,
        background_color="#070c16",
    )
    api.set_window(window)

    def on_loaded():
        window.show()
        # Start auto-discovery after UI is ready
        api.start_discovery()

    window.events.loaded += on_loaded
    threading.Timer(5.0, lambda: window.show()).start()

    try:
        webview.start(debug=False)
    finally:
        api.stop_discovery()
        if instance_lock:
            try:
                instance_lock.close()
            except Exception:
                pass
        logger.info("Shutdown Panel Client exited")


if __name__ == "__main__":
    main()
