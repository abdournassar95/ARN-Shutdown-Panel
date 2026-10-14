"""
Shutdown Panel — Build Tool (Python Edition)
Builds Host Server, Remote Client, and Inno Setup Installer.
"""

import argparse
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent


def ensure_pyinstaller():
    """Installs PyInstaller when missing."""
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller not found — installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def generate_icon() -> str:
    """Creates assets/icon.ico from the tray glyph (if not already present)."""
    icon_path = HERE / "assets" / "icon.ico"
    if icon_path.exists():
        return str(icon_path)
    try:
        from PIL import Image, ImageDraw

        base = Image.new("RGBA", (256, 256), color=(10, 22, 40, 255))
        draw = ImageDraw.Draw(base)
        draw.ellipse((14, 14, 242, 242), fill=(12, 20, 36, 255),
                     outline=(34, 211, 238, 255), width=14)
        draw.arc((56, 56, 200, 200), start=300, end=240, fill=(34, 211, 238, 255), width=18)
        draw.line((128, 40, 128, 122), fill=(34, 211, 238, 255), width=18)
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        base.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        print("Icon generated: assets/icon.ico")
        return str(icon_path)
    except Exception as e:
        print(f"Icon generation skipped ({e}) — building without an icon.")
        return ""


def find_iscc() -> Optional[pathlib.Path]:
    """Finds Inno Setup Compiler (ISCC.exe) in standard system locations."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        pathlib.Path("C:/Program Files/Inno Setup 7/ISCC.exe"),
        pathlib.Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        pathlib.Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
        pathlib.Path("C:/Program Files (x86)/Inno Setup 5/ISCC.exe"),
        pathlib.Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe" if local_app_data else None,
        pathlib.Path(local_app_data) / "Programs" / "Antigravity IDE" / "resources" / "app" / "node_modules" / "innosetup" / "bin" / "ISCC.exe" if local_app_data else None,
    ]
    for c in candidates:
        if c and c.exists():
            return c
    which = shutil.which("iscc")
    if which:
        return pathlib.Path(which)
    return None


def sign_executable(file_path: pathlib.Path):
    """Signs an executable with ARN Technology digital certificate if present."""
    if not file_path.exists():
        return
    ps_cmd = f"""
    $cert = Get-ChildItem -Path "Cert:\\CurrentUser\\My" | Where-Object {{ $_.Subject -match "CN=ARN Technology" -and $_.NotAfter -gt (Get-Date) }} | Select-Object -First 1
    if ($cert) {{
        try {{
            Set-AuthenticodeSignature -Certificate $cert -FilePath "{file_path}" -TimestampServer "http://timestamp.digicert.com" -ErrorAction Stop | Out-Null
            Write-Host "  Digitally signed: {file_path.name}"
        }} catch {{
            Set-AuthenticodeSignature -Certificate $cert -FilePath "{file_path}" | Out-Null
            Write-Host "  Digitally signed (no timestamp): {file_path.name}"
        }}
    }}
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], check=False)
    except Exception:
        pass


def build_server():
    print("\n📦 [1/3] Building Host Server: dist/ShutdownPanel.exe ...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(HERE / "ShutdownPanel.spec"),
    ]
    subprocess.check_call(cmd)
    out = HERE / "dist" / "ShutdownPanel.exe"
    sign_executable(out)
    print("✅ Host Server build complete: dist/ShutdownPanel.exe")


def build_client():
    print("\n📦 [2/3] Building Remote Client: dist/ShutdownPanelClient.exe ...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(HERE / "ShutdownPanelClient.spec"),
    ]
    subprocess.check_call(cmd)
    out = HERE / "dist" / "ShutdownPanelClient.exe"
    sign_executable(out)
    print("✅ Remote Client build complete: dist/ShutdownPanelClient.exe")


def build_installer():
    print("\n💿 [3/3] Compiling Inno Setup unified installer ...")
    iscc = find_iscc()
    if not iscc:
        print("⚠️ Inno Setup (ISCC.exe) not found on system.")
        print("   To build the installer, install Inno Setup 6 or 7, or run:")
        print("   winget install --id JRSoftware.InnoSetup -e")
        return False

    iss_file = HERE / "installer.iss"
    if not iss_file.exists():
        print(f"❌ Installer script not found: {iss_file}")
        return False

    cmd = [str(iscc), str(iss_file)]
    print(f"Running: {iscc} {iss_file}")
    subprocess.check_call(cmd)
    setup_file = HERE / "dist" / "ShutdownPanel_Setup_v2.0.0.exe"
    sign_executable(setup_file)
    print("✅ Installer build complete! Generated at: dist/ShutdownPanel_Setup_v2.0.0.exe")
    return True


def main():
    parser = argparse.ArgumentParser(description="Shutdown Panel Build Tool")
    parser.add_argument("--server", action="store_true", help="Build Host Server executable only")
    parser.add_argument("--client", action="store_true", help="Build Remote Client executable only")
    parser.add_argument("--installer", action="store_true", help="Build Inno Setup installer only")
    args = parser.parse_args()

    build_all = not (args.server or args.client or args.installer)

    ensure_pyinstaller()
    generate_icon()

    if build_all or args.server:
        build_server()

    if build_all or args.client:
        build_client()

    if build_all or args.installer:
        build_installer()

    print("\n🎉 All requested build tasks completed successfully!")


if __name__ == "__main__":
    main()
