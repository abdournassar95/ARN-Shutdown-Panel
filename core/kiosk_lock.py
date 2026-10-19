"""
Kiosk and System Lockdown Module for Windows.
Enforces true full-screen lock screen:
1. Covers all monitors (Virtual Screen) and layers above taskbars.
2. Hides the Windows Taskbar (Shell_TrayWnd & Shell_SecondaryTrayWnd).
3. Strips window frames, borders, and menus to prevent moving or resizing.
4. Focus Guard daemon: immediately re-asserts foreground window if user tries to switch away.
5. Low-level keyboard hook: intercepts and suppresses Windows Key, Alt+Tab, Alt+Esc, Ctrl+Esc, Alt+F4.
"""

import sys
import threading
import time
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

# Fallbacks defined at module level so the manager stays import-safe and
# callable on non-Windows platforms (the Win32 calls themselves are no-ops).
SW_HIDE = 0
SW_SHOW = 5

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    # Windows Constants
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    VK_TAB = 0x09
    VK_ESCAPE = 0x1B
    VK_LWIN = 0x5B
    VK_RWIN = 0x5C
    VK_F4 = 0x73

    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_POPUP = 0x80000000
    WS_VISIBLE = 0x10000000
    WS_THICKFRAME = 0x00040000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080

    HWND_TOPMOST = -1
    SWP_SHOWWINDOW = 0x0040
    SWP_FRAMECHANGED = 0x0020
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]


class KioskLockManager:
    _instance: Optional["KioskLockManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._is_locked = False
        self._hwnd: Optional[int] = None
        self._hook_handle = None
        self._hook_proc_ref = None  # prevent GC of callback
        self._guard_thread: Optional[threading.Thread] = None
        self._stop_guard = threading.Event()
        self._hook_thread: Optional[threading.Thread] = None
        self._hook_thread_id: Optional[int] = None

    @classmethod
    def get_instance(cls) -> "KioskLockManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = KioskLockManager()
            return cls._instance

    def lock(self, hwnd_or_title: int | str):
        """Enforces full-screen kiosk lock on the given window handle or title."""
        if not IS_WINDOWS:
            self._is_locked = True
            return

        with self._lock:
            if self._is_locked:
                return
            self._is_locked = True
            self._stop_guard.clear()

        # Resolve HWND if string passed
        hwnd = hwnd_or_title
        if isinstance(hwnd_or_title, str):
            hwnd = user32.FindWindowW(None, hwnd_or_title)
            if not hwnd:
                time.sleep(0.1)
                hwnd = user32.FindWindowW(None, hwnd_or_title)

        self._hwnd = hwnd
        if not hwnd:
            return

        # 1. Hide Windows Taskbar(s)
        self._set_taskbars_visible(False)

        # 2. Cover all screens (Virtual Screen) and strip window decorations
        self._apply_kiosk_geometry(hwnd)

        # 3. Disable system menu (prevents move, size, close)
        try:
            hmenu = user32.GetSystemMenu(hwnd, False)
            if hmenu:
                # SC_MOVE = 0xF010, SC_SIZE = 0xF000, SC_CLOSE = 0xF060
                user32.DeleteMenu(hmenu, 0xF010, 0x0000)
                user32.DeleteMenu(hmenu, 0xF000, 0x0000)
                user32.DeleteMenu(hmenu, 0xF060, 0x0000)
        except Exception:
            pass

        # 4. Install Low-Level Keyboard Hook
        self._install_keyboard_hook()

        # 5. Start Focus Guard Daemon
        self._guard_thread = threading.Thread(
            target=self._focus_guard_loop, args=(hwnd,), daemon=True, name="KioskFocusGuard"
        )
        self._guard_thread.start()

    def unlock(self, hwnd_or_title: Optional[int | str] = None):
        """Releases the kiosk lock and restores normal desktop interaction."""
        if not IS_WINDOWS:
            self._is_locked = False
            return

        with self._lock:
            if not self._is_locked:
                return
            self._is_locked = False
            self._stop_guard.set()

        # 1. Stop Keyboard Hook
        self._uninstall_keyboard_hook()

        # 2. Restore Taskbar(s)
        self._set_taskbars_visible(True)

        self._hwnd = None

    def _apply_kiosk_geometry(self, hwnd: int):
        """Sizes and positions window to cover the entire virtual screen, above everything."""
        try:
            # Query entire virtual screen dimensions
            vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            if vw <= 0 or vh <= 0:
                vw = user32.GetSystemMetrics(0)
                vh = user32.GetSystemMetrics(1)
                vx, vy = 0, 0

            # Strip thickframe and caption, make pure WS_POPUP | WS_VISIBLE
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            style = (style | WS_POPUP | WS_VISIBLE) & ~(WS_THICKFRAME | WS_CAPTION | WS_SYSMENU)
            user32.SetWindowLongW(hwnd, GWL_STYLE, style)

            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style = (ex_style | WS_EX_TOPMOST) & ~WS_EX_TOOLWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

            # Move and size to full virtual screen
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                int(vx),
                int(vy),
                int(vw),
                int(vh),
                SWP_SHOWWINDOW | SWP_FRAMECHANGED,
            )
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
        except Exception:
            pass

    def _set_taskbars_visible(self, visible: bool):
        """Hides or shows the primary and secondary taskbars."""
        cmd = SW_SHOW if visible else SW_HIDE
        try:
            tray = user32.FindWindowW("Shell_TrayWnd", None)
            if tray:
                user32.ShowWindow(tray, cmd)
            # Multi-monitor secondary taskbars
            sec_tray = user32.FindWindowW("Shell_SecondaryTrayWnd", None)
            if sec_tray:
                user32.ShowWindow(sec_tray, cmd)
        except Exception:
            pass

    def _focus_guard_loop(self, hwnd: int):
        """Continuously re-asserts foreground window if user tries to switch away."""
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        while not self._stop_guard.is_set():
            try:
                fg = user32.GetForegroundWindow()
                if fg != hwnd and user32.IsWindow(hwnd):
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, vx, vy, vw, vh, SWP_SHOWWINDOW)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
            except Exception:
                pass
            time.sleep(0.12)

    def _install_keyboard_hook(self):
        """Installs the low-level hook on a dedicated thread with a Win32 message loop."""
        ready_evt = threading.Event()

        def hook_worker():
            def hook_cb(nCode, wParam, lParam):
                if nCode >= 0:
                    kb = KBDLLHOOKSTRUCT.from_address(lParam)
                    vk = kb.vkCode
                    flags = kb.flags
                    is_alt = bool(flags & 0x20)

                    # Block Windows keys
                    if vk in (VK_LWIN, VK_RWIN):
                        return 1

                    # Block Alt+Tab
                    if vk == VK_TAB and is_alt:
                        return 1

                    # Block Alt+Esc, Ctrl+Esc
                    if vk == VK_ESCAPE:
                        ctrl_pressed = bool(user32.GetKeyState(0x11) & 0x8000)
                        if is_alt or ctrl_pressed:
                            return 1

                    # Block Alt+F4
                    if vk == VK_F4 and is_alt:
                        return 1

                return user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

            self._hook_proc_ref = HOOKPROC(hook_cb)
            self._hook_thread_id = kernel32.GetCurrentThreadId()
            h_mod = kernel32.GetModuleHandleW(None)
            self._hook_handle = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._hook_proc_ref, h_mod, 0
            )

            ready_evt.set()

            # Win32 message loop for the hook
            msg = wintypes.MSG()
            while not self._stop_guard.is_set():
                # Peek and dispatch messages
                if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
                self._hook_handle = None

        self._hook_thread = threading.Thread(
            target=hook_worker, daemon=True, name="KioskKeyboardHook"
        )
        self._hook_thread.start()
        ready_evt.wait(timeout=1.0)

    def _uninstall_keyboard_hook(self):
        """Uninstalls the low-level hook."""
        self._stop_guard.set()
        if self._hook_handle:
            try:
                user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                pass
            self._hook_handle = None
        self._hook_proc_ref = None
