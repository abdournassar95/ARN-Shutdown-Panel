"""
Input and Media Controller module (v2).
Low-latency mouse, keyboard, media, volume and brightness controls for
Windows (native SendInput/ctypes) with pyautogui fallbacks for Linux/macOS.
"""

import subprocess
import sys
import time
from typing import Dict, Optional

try:
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:  # ImportError and headless-display errors
    pyautogui = None

from core.app_logger import get_logger

IS_WINDOWS = sys.platform == "win32"

# Virtual Key Codes (platform-independent integers)
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# Special key name -> Virtual Key code
VK_MAP = {
    "enter": 0x0D, "return": 0x0D,
    "backspace": 0x08, "bs": 0x08,
    "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "pgup": 0x21, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "meta": 0x5B,
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "shift": 0x10,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "printscreen": 0x2C, "prtsc": 0x2C,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
}

# Modifier key codes for hotkeys
MOD_MAP = {
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "option": 0x12,
    "shift": 0x10,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "meta": 0x5B,
}

if IS_WINDOWS:
    import ctypes
    from ctypes import (
        HRESULT,
        POINTER,
        Structure,
        byref,
        c_float,
        c_int,
        c_void_p,
        cast,
        wintypes,
    )

    user32 = ctypes.windll.user32
    ole32 = ctypes.windll.ole32

    # Core Audio COM GUIDs and structures
    class GUID(Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

        def __init__(self, l, w1, w2, b1, b2, b3, b4, b5, b6, b7, b8):
            super().__init__(l, w1, w2, (wintypes.BYTE * 8)(b1, b2, b3, b4, b5, b6, b7, b8))

    CLSID_MMDeviceEnumerator = GUID(0xBCDE0395, 0xE52F, 0x467C, 0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E)
    IID_IMMDeviceEnumerator = GUID(0xA95664D2, 0x9614, 0x4F35, 0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6)
    IID_IAudioEndpointVolume = GUID(0x5CDF2C82, 0x841E, 0x4546, 0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22, 0x9A)

    # Mouse flags
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800

    # SendInput structures (union must include ALL input types so that
    # sizeof(INPUT) is correct on 64-bit builds)
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [
            ("type", wintypes.DWORD),
            ("u", _INPUT_UNION),
        ]


def enable_dpi_awareness() -> bool:
    """Makes the process DPI-aware so coordinates match physical pixels."""
    if not IS_WINDOWS:
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
        return True
    except Exception:
        try:
            user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


class InputController:
    """Manages virtual mouse, keyboard, media, volume and brightness controls."""

    # ------------------------------------------------------------------
    # Mouse Controls
    # ------------------------------------------------------------------
    @classmethod
    def mouse_move_rel(cls, dx: int, dy: int):
        if IS_WINDOWS:
            user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)
        elif pyautogui:
            pyautogui.moveRel(dx, dy)

    @classmethod
    def mouse_move_to(cls, x: int, y: int):
        if IS_WINDOWS:
            user32.SetCursorPos(int(x), int(y))
        elif pyautogui:
            pyautogui.moveTo(x, y)

    @classmethod
    def _mouse_flags(cls, button: str):
        b = button.lower()
        if IS_WINDOWS:
            if b == "left":
                return MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
            if b == "right":
                return MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
            return MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        return None

    @classmethod
    def mouse_click(cls, button: str = "left", double: bool = False):
        b = button.lower()
        if IS_WINDOWS:
            down_flag, up_flag = cls._mouse_flags(b)
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            if double:
                time.sleep(0.05)
                user32.mouse_event(down_flag, 0, 0, 0, 0)
                user32.mouse_event(up_flag, 0, 0, 0, 0)
        elif pyautogui:
            pyautogui.click(button=b, clicks=2 if double else 1)

    @classmethod
    def mouse_down(cls, button: str = "left"):
        b = button.lower()
        if IS_WINDOWS:
            down_flag, _ = cls._mouse_flags(b)
            user32.mouse_event(down_flag, 0, 0, 0, 0)
        elif pyautogui:
            pyautogui.mouseDown(button=b)

    @classmethod
    def mouse_up(cls, button: str = "left"):
        b = button.lower()
        if IS_WINDOWS:
            _, up_flag = cls._mouse_flags(b)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
        elif pyautogui:
            pyautogui.mouseUp(button=b)

    @classmethod
    def mouse_scroll(cls, dy: int):
        """Scrolls vertically (positive = up, negative = down)."""
        if IS_WINDOWS:
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(dy * 120), 0)
        elif pyautogui:
            pyautogui.scroll(int(dy))  # pyautogui units are "clicks", not WHEEL_DELTA

    # ------------------------------------------------------------------
    # Keyboard Controls (native SendInput, correct x64 layout)
    # ------------------------------------------------------------------
    @classmethod
    def _send_keyboard_inputs(cls, events) -> bool:
        """
        events: list of (vk, scan, flags). Sends everything in ONE SendInput call.
        Returns True on success.
        """
        if not IS_WINDOWS:
            return False
        n = len(events)
        inputs = (INPUT * n)()
        for i, (vk, scan, flags) in enumerate(events):
            inputs[i].type = INPUT_KEYBOARD
            inputs[i].ki.wVk = vk
            inputs[i].ki.wScan = scan
            inputs[i].ki.dwFlags = flags
            inputs[i].ki.time = 0
        sent = user32.SendInput(n, inputs, ctypes.sizeof(INPUT))
        if sent != n:
            get_logger().warning("SendInput delivered %s/%s events", sent, n)
            return False
        return True

    @classmethod
    def type_unicode_char(cls, char: str):
        """Sends a single Unicode character (down+up) via SendInput.
        Characters above U+FFFF are split into UTF-16 surrogate pairs."""
        if not IS_WINDOWS:
            if pyautogui:
                pyautogui.write(char)
            return
        code = ord(char)
        if code > 0xFFFF:
            # Surrogate pair: Windows SendInput expects two 16-bit UNICODE events
            high = 0xD800 + ((code - 0x10000) >> 10)
            low = 0xDC00 + ((code - 0x10000) & 0x3FF)
            cls._send_keyboard_inputs([
                (0, high, KEYEVENTF_UNICODE),
                (0, low, KEYEVENTF_UNICODE),
                (0, low, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                (0, high, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ])
        else:
            cls._send_keyboard_inputs([
                (0, code, KEYEVENTF_UNICODE),
                (0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ])

    @classmethod
    def type_text(cls, text: str):
        """
        Types arbitrary text (Arabic, English, emoji, all Unicode) in a single
        batched SendInput call — fast and reliable.
        Characters above U+FFFF are split into UTF-16 surrogate pairs.
        """
        if not text:
            return
        if not IS_WINDOWS:
            if pyautogui:
                pyautogui.write(text)
            return
        events = []
        for ch in text:
            code = ord(ch)
            if code > 0xFFFF:
                high = 0xD800 + ((code - 0x10000) >> 10)
                low = 0xDC00 + ((code - 0x10000) & 0x3FF)
                events.append((0, high, KEYEVENTF_UNICODE))
                events.append((0, low, KEYEVENTF_UNICODE))
                events.append((0, low, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
                events.append((0, high, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            else:
                events.append((0, code, KEYEVENTF_UNICODE))
                events.append((0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        cls._send_keyboard_inputs(events)

    @classmethod
    def _resolve_vk(cls, key: str) -> Optional[int]:
        """Maps a key name or single character to a Virtual Key code."""
        k = key.strip().lower()
        if k in VK_MAP:
            return VK_MAP[k]
        if len(k) == 1:
            ch = k.upper()
            if ch.isascii() and (ch.isalpha() or ch.isdigit()):
                return ord(ch)  # VK codes for 'A'-'Z' / '0'-'9' match ASCII
        return None

    @classmethod
    def key_press(cls, key: str) -> bool:
        """Presses a single key. Returns True when the input was delivered."""
        k = key.strip().lower()
        if k in ("win", "windows", "super", "meta"):
            k = "win"
        if pyautogui:
            try:
                pyautogui.press(k)
                return True
            except Exception:
                pass
        vk = cls._resolve_vk(k)
        if vk is not None:
            return cls._send_keyboard_inputs(
                [(vk, 0, 0), (vk, 0, KEYEVENTF_KEYUP)]
            )
        # Fallback for printable non-ASCII characters
        if len(key) == 1:
            cls.type_unicode_char(key)
            return True
        return False

    @classmethod
    def hotkey(cls, *keys: str) -> bool:
        """Executes a key combination like ctrl+c, alt+tab, win+d."""
        cleaned = [k.strip().lower() for k in keys if k and k.strip()]
        if not cleaned:
            return False
        if pyautogui:
            try:
                pyautogui.hotkey(*cleaned)
                return True
            except Exception:
                pass
        if not IS_WINDOWS:
            return False

        events = []
        held = []
        # Hold modifiers down
        for name in cleaned[:-1] if len(cleaned) > 1 else []:
            vk = MOD_MAP.get(name)
            if vk is not None and vk not in held:
                held.append(vk)
                events.append((vk, 0, 0))
        # Final key
        final = cleaned[-1]
        vk = cls._resolve_vk(final)
        if vk is None and len(final) == 1:
            # Unicode character as the final key
            events.append((0, ord(final), KEYEVENTF_UNICODE))
            events.append((0, ord(final), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        elif vk is not None:
            events.append((vk, 0, 0))
            events.append((vk, 0, KEYEVENTF_KEYUP))
        # Release modifiers in reverse order
        for vk in reversed(held):
            events.append((vk, 0, KEYEVENTF_KEYUP))
        return cls._send_keyboard_inputs(events)

    # ------------------------------------------------------------------
    # Media & Volume Controls
    # ------------------------------------------------------------------
    @classmethod
    def _send_vk(cls, vk: int):
        if IS_WINDOWS:
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, 2, 0)
        elif pyautogui:
            try:
                pyautogui.press(
                    {
                        0xAD: "volumemute", 0xAE: "volumedown", 0xAF: "volumeup",
                        0xB0: "nexttrack", 0xB1: "prevtrack",
                        0xB2: "stop", 0xB3: "playpause",
                    }.get(vk, "")
                )
            except Exception:
                pass

    @classmethod
    def media_play_pause(cls):
        cls._send_vk(VK_MEDIA_PLAY_PAUSE)

    @classmethod
    def media_next(cls):
        cls._send_vk(VK_MEDIA_NEXT_TRACK)

    @classmethod
    def media_prev(cls):
        cls._send_vk(VK_MEDIA_PREV_TRACK)

    @classmethod
    def media_stop(cls):
        cls._send_vk(VK_MEDIA_STOP)

    @classmethod
    def volume_up(cls, steps: int = 2):
        for _ in range(steps):
            cls._send_vk(VK_VOLUME_UP)

    @classmethod
    def volume_down(cls, steps: int = 2):
        for _ in range(steps):
            cls._send_vk(VK_VOLUME_DOWN)

    @classmethod
    def volume_mute(cls):
        """Toggles system master volume mute state."""
        if IS_WINDOWS:
            try:
                endpointVolume = cls._get_audio_endpoint_volume()
                if endpointVolume:
                    vol_vtable = cast(cast(endpointVolume, POINTER(c_void_p)).contents, POINTER(c_void_p))
                    GetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.BOOL))(vol_vtable[15])
                    SetMute = ctypes.WINFUNCTYPE(HRESULT, c_void_p, wintypes.BOOL, c_void_p)(vol_vtable[14])
                    is_muted = wintypes.BOOL()
                    if GetMute(endpointVolume, byref(is_muted)) == 0:
                        SetMute(endpointVolume, not is_muted.value, None)
                        return
            except Exception as e:
                get_logger().debug("volume_mute failed: %s", e)
        cls._send_vk(VK_VOLUME_MUTE)

    # ------------------------------------------------------------------
    # Exact volume / brightness via Windows Native COM & WMI
    # ------------------------------------------------------------------
    @classmethod
    def _get_audio_endpoint_volume(cls):
        """Returns the IAudioEndpointVolume COM interface or None on Windows."""
        if not IS_WINDOWS:
            return None
        try:
            ole32.CoInitialize(None)
            enumerator = c_void_p()
            hr = ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, 1, byref(IID_IMMDeviceEnumerator), byref(enumerator))
            if hr != 0 or not enumerator:
                return None

            vtable = cast(cast(enumerator, POINTER(c_void_p)).contents, POINTER(c_void_p))
            GetDefaultAudioEndpoint = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_int, c_int, POINTER(c_void_p))(vtable[4])
            device = c_void_p()
            hr = GetDefaultAudioEndpoint(enumerator, 0, 1, byref(device))
            if hr != 0 or not device:
                return None

            dev_vtable = cast(cast(device, POINTER(c_void_p)).contents, POINTER(c_void_p))
            Activate = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(dev_vtable[3])
            endpointVolume = c_void_p()
            hr = Activate(device, byref(IID_IAudioEndpointVolume), 23, None, byref(endpointVolume))
            if hr != 0 or not endpointVolume:
                return None

            return endpointVolume
        except Exception as e:
            get_logger().debug("COM Audio init failed: %s", e)
            return None

    @classmethod
    def set_volume_percent(cls, percent: int) -> bool:
        """Sets the exact master volume (0-100) via Windows Core Audio COM API."""
        target = max(0, min(100, int(percent)))
        if IS_WINDOWS:
            try:
                endpointVolume = cls._get_audio_endpoint_volume()
                if endpointVolume:
                    vol_vtable = cast(cast(endpointVolume, POINTER(c_void_p)).contents, POINTER(c_void_p))
                    SetMasterVolumeLevelScalar = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vol_vtable[7])
                    hr = SetMasterVolumeLevelScalar(endpointVolume, float(target / 100.0), None)
                    return hr == 0
            except Exception as e:
                get_logger().debug("set_volume_percent failed: %s", e)
        return False

    @classmethod
    def get_volume_percent(cls) -> Optional[float]:
        """Reads the current master volume percent via Windows Core Audio COM API."""
        if IS_WINDOWS:
            try:
                endpointVolume = cls._get_audio_endpoint_volume()
                if endpointVolume:
                    vol_vtable = cast(cast(endpointVolume, POINTER(c_void_p)).contents, POINTER(c_void_p))
                    GetMasterVolumeLevelScalar = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vol_vtable[9])
                    curr = c_float()
                    hr = GetMasterVolumeLevelScalar(endpointVolume, byref(curr))
                    if hr == 0:
                        return round(curr.value * 100.0, 1)
            except Exception as e:
                get_logger().debug("get_volume_percent failed: %s", e)
        return None

    @classmethod
    def set_brightness_percent(cls, percent: int) -> bool:
        """Sets display brightness (0-100) via WMI."""
        target = max(0, min(100, int(percent)))
        if not IS_WINDOWS:
            return False
        try:
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                    f".WmiSetBrightness(1, {target})",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            return True
        except Exception as e:
            get_logger().debug("brightness failed: %s", e)
            return False

    # ------------------------------------------------------------------
    @classmethod
    def get_screen_size(cls) -> Dict[str, int]:
        """Returns primary screen dimensions in physical pixels."""
        if IS_WINDOWS:
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return {"width": w, "height": h}
        if pyautogui:
            try:
                w, h = pyautogui.size()
                return {"width": w, "height": h}
            except Exception:
                pass
        return {"width": 1920, "height": 1080}

    @classmethod
    def get_dpi_scale(cls) -> float:
        """Returns the system DPI scale factor (1.0, 1.25, 1.5, ...)."""
        if IS_WINDOWS:
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
                return max(1.0, round(dpi / 96.0, 2))
            except Exception:
                return 1.0
        return 1.0
