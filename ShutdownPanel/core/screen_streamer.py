"""
Screen capture and live streaming module (v2).
Uses mss (fast native capture) with a Pillow fallback,
providing low-latency MJPEG frames and snapshot captures.
"""

import io
import threading
import time
from typing import Optional

from PIL import Image

try:
    import mss

    MSS_AVAILABLE = True
except Exception:  # mss may fail on headless systems
    mss = None
    MSS_AVAILABLE = False

from core.app_logger import get_logger


class ScreenStreamer:
    """Captures and compresses the screen for streaming and snapshots."""

    _mss_lock = threading.Lock()
    _mss_instance = None

    @classmethod
    def _get_mss(cls):
        """Shared mss instance (mss is not thread-safe; guarded by a lock)."""
        if not MSS_AVAILABLE:
            return None
        with cls._mss_lock:
            if cls._mss_instance is None:
                cls._mss_instance = getattr(mss, "MSS", mss.mss)()
            return cls._mss_instance

    # ------------------------------------------------------------------
    @staticmethod
    def _grab_pil() -> Image.Image:
        from PIL import ImageGrab

        return ImageGrab.grab()

    @classmethod
    def _grab_mss(cls, sct) -> Optional[Image.Image]:
        try:
            with cls._mss_lock:
                shot = sct.grab(sct.monitors[1])  # primary monitor
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as e:
            get_logger().debug("mss grab failed: %s", e)
            return None

    @classmethod
    def capture_image(cls, scale: float = 0.6, sct=None) -> Image.Image:
        """Captures the primary display as a PIL RGB image (with error placeholder)."""
        img: Optional[Image.Image] = None
        if sct is not None:
            img = cls._grab_mss(sct)
        elif MSS_AVAILABLE:
            img = cls._grab_mss(cls._get_mss())
        if img is None:
            try:
                img = cls._grab_pil()
            except Exception as e:
                get_logger().debug("PIL grab failed: %s", e)
                img = None
        if img is None:
            return Image.new("RGB", (640, 360), color=(20, 20, 30))

        if img.mode != "RGB":
            img = img.convert("RGB")
        if 0.1 <= scale < 1.0:
            new_w = max(1, int(img.width * scale))
            new_h = max(1, int(img.height * scale))
            img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
        return img

    @classmethod
    def capture_frame(cls, scale: float = 0.6, quality: int = 55, sct=None) -> bytes:
        """Captures the primary display and encodes it into JPEG bytes."""
        try:
            img = cls.capture_image(scale=scale, sct=sct)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=False)
            return buf.getvalue()
        except Exception as e:
            get_logger().debug("frame capture failed: %s", e)
            err_img = Image.new("RGB", (640, 360), color=(20, 20, 30))
            buf = io.BytesIO()
            err_img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()

    # ------------------------------------------------------------------
    @classmethod
    def generate_mjpeg_frames(
        cls,
        fps: int = 15,
        scale: float = 0.6,
        quality: int = 55,
        max_duration_secs: int = 1800,
    ):
        """Yields multipart HTTP MJPEG frames continuously (single mss session)."""
        delay = 1.0 / max(1, min(fps, 30))
        start_time = time.time()

        # One capture session for the whole stream (much faster per frame)
        sct = None
        if MSS_AVAILABLE:
            try:
                with cls._mss_lock:
                    sct = getattr(mss, "MSS", mss.mss)()
            except Exception:
                sct = None

        try:
            while (time.time() - start_time) < max_duration_secs:
                t0 = time.time()
                frame = cls.capture_frame(scale=scale, quality=quality, sct=sct)

                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: "
                    + str(len(frame)).encode("ascii")
                    + b"\r\n\r\n"
                )
                yield header + frame + b"\r\n"

                elapsed = time.time() - t0
                sleep_time = delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            if sct is not None:
                try:
                    sct.close()
                except Exception:
                    pass
