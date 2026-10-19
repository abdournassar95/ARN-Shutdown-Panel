"""
Command planning and execution module (v2).
Provides platform-independent command construction and execution for
Windows, Linux, and macOS with strict validation and exit-code checking.
"""

import getpass
import os
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Windows shutdown.exe exit code: no pending shutdown to abort
WIN_ERROR_NO_SHUTDOWN_PENDING = 1116


class Commander:
    @staticmethod
    def get_os() -> str:
        if sys.platform == "win32":
            return "windows"
        elif sys.platform == "darwin":
            return "macos"
        return "linux"

    @classmethod
    def is_safe_host(cls, host: str) -> bool:
        if not host or len(host) > 253:
            return False
        # Only allow alphanumeric, dot, dash, colon, underscore
        return all(c.isalnum() or c in ".-:_" for c in host)

    @staticmethod
    def _result(
        program: str,
        args: list,
        display: str,
        action: str,
    ) -> Dict[str, Any]:
        return {
            "program": program,
            "args": args,
            "display": display,
            "action": action,
            "supported": True,
        }

    @classmethod
    def plan(
        cls,
        action: str,
        delay_secs: int = 0,
        force: bool = False,
        host: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Builds the exact command array and display string for the specified action."""
        try:
            delay = max(0, min(int(delay_secs), 86400))
        except (TypeError, ValueError):
            raise ValueError("delay_secs must be an integer") from None

        target_os = cls.get_os()

        if host and host.strip():
            h = host.strip()
            if not cls.is_safe_host(h):
                raise ValueError("Invalid hostname or IP address")
            if target_os != "windows":
                raise ValueError("Remote execution only supported on Windows")
            if action not in ("shutdown", "restart"):
                raise ValueError(f"Remote action '{action}' is not supported")
            flag = "/r" if action == "restart" else "/s"
            args = ["shutdown.exe", flag, "/m", f"\\\\{h}", "/t", str(delay)]
            if force:
                args.append("/f")
            return cls._result(args[0], args[1:], " ".join(args), action)

        # -------------------------------------------------- Local: Windows
        if target_os == "windows":
            if action in ("shutdown", "restart"):
                flag = "/s" if action == "shutdown" else "/r"
                args = ["shutdown.exe", flag, "/t", str(delay)]
                if force:
                    args.append("/f")
                return cls._result(args[0], args[1:], " ".join(args), action)

            if action == "lock":
                return cls._result(
                    "rundll32.exe",
                    ["user32.dll,LockWorkStation"],
                    "rundll32.exe user32.dll,LockWorkStation",
                    action,
                )

            if action in ("signout", "sign_out"):
                return cls._result(
                    "shutdown.exe", ["/l"], "shutdown.exe /l", action
                )

            if action == "hibernate":
                return cls._result(
                    "shutdown.exe", ["/h"], "shutdown.exe /h", action
                )

            if action == "sleep":
                f = "true" if force else "false"
                ps_script = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "[System.Windows.Forms.Application]::SetSuspendState("
                    f"false,{f},'false')"
                )
                args = [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    ps_script,
                ]
                return cls._result(
                    args[0], args[1:], f"SetSuspendState(false,{f})", action
                )

            if action == "display_off":
                ps_script = (
                    "$code = '[DllImport(\"user32.dll\")] public static extern int SendMessage(int hWnd, int hMsg, int wParam, int lParam);';"
                    "$type = Add-Type -MemberDefinition $code -Name \"Win32SendMessage\" -Namespace \"Win32Functions\" -PassThru;"
                    "$type::SendMessage(-1, 0x0112, 0xF170, 2)"
                )
                args = ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script]
                return cls._result(args[0], args[1:], "Turn off display", action)

            raise ValueError(f"Unknown action '{action}'")

        # -------------------------------------------------- Local: Linux
        if target_os == "linux":
            mapping = {
                "shutdown": ["systemctl", "poweroff"],
                "restart": ["systemctl", "reboot"],
                "sleep": ["systemctl", "suspend"],
                "hibernate": ["systemctl", "hibernate"],
                "display_off": ["xset", "dpms", "force", "off"],
                "lock": ["loginctl", "lock-session"],
                "signout": [
                    "loginctl",
                    "terminate-user",
                    os.environ.get("USER") or getpass.getuser(),
                ],
            }
            if action not in mapping:
                raise ValueError(f"Action '{action}' not supported on Linux")
            cmd = [c for c in mapping[action] if c != ""]
            return cls._result(cmd[0], cmd[1:], " ".join(cmd), action)

        # -------------------------------------------------- Local: macOS
        if target_os == "macos":
            mapping = {
                "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
                "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
                "sleep": ["pmset", "sleepnow"],
                "hibernate": ["pmset", "sleepnow"],
                "display_off": ["pmset", "displaysleepnow"],
                "lock": [
                    "/System/Library/CoreServices/Menu Extras/User.menu/Contents/"
                    "Resources/CGSession",
                    "-suspend",
                ],
                "signout": ["osascript", "-e", 'tell app "System Events" to log out'],
            }
            if action not in mapping:
                raise ValueError(f"Action '{action}' not supported on macOS")
            cmd = mapping[action]
            return cls._result(cmd[0], cmd[1:], " ".join(cmd), action)

        raise ValueError(f"Unsupported OS: {target_os}")

    @classmethod
    def plan_abort(cls) -> Dict[str, Any]:
        if cls.get_os() == "windows":
            return cls._result("shutdown.exe", ["/a"], "shutdown.exe /a", "abort")
        return {
            "program": "",
            "args": [],
            "display": "abort not supported on this OS",
            "action": "abort",
            "supported": False,
        }

    @classmethod
    def execute(
        cls, plan_obj: Dict[str, Any], wait_timeout: float = 5.0
    ) -> Tuple[bool, str, Optional[int], Optional[str]]:
        """
        Executes a planned command and verifies its exit code.
        Returns (ok, display, pid, error).
        - ok=False with an error message when the command fails or cannot start.
        - Commands still running after wait_timeout (e.g. suspend in progress)
          are considered successfully launched.
        """
        program = plan_obj.get("program")
        args = plan_obj.get("args", []) or []
        display = plan_obj.get("display", "")

        if not program:
            return False, display, None, "No program specified"

        full_cmd = [program] + list(args)
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=flags,
            )
        except Exception as e:
            return False, display, None, str(e)

        pid = proc.pid
        try:
            # Bounded wait: keeps the UI responsive while still catching fast failures.
            _, err_bytes = proc.communicate(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            # Still running after the grace period (sleep/hibernate, remote RPC...).
            return True, display, pid, None

        err_text = (err_bytes or b"").decode("utf-8", errors="replace").strip()
        rc = proc.returncode

        if rc == 0:
            return True, display, pid, None

        if sys.platform == "win32" and rc == WIN_ERROR_NO_SHUTDOWN_PENDING:
            return True, display, pid, None

        return False, display, pid, err_text or f"Command failed with exit code {rc}"
