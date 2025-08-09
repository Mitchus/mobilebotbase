from __future__ import annotations

"""
StreamBot: drop-in Bot replacement that reads frames from a live stream
(adb exec-out screenrecord, scrcpy, local video, or webcam) instead of
per-call screencaps. Keeps the same high-level API for matching and taps.

Requires: numpy, opencv-python, and PyAV (for adb/scrcpy sources).
"""

import contextlib
import subprocess
import threading
import time
from typing import Optional

import cv2
import numpy as np

try:
    import av  # type: ignore
except Exception:  # pragma: no cover
    av = None  # type: ignore

from bot import Bot, rect_center, draw_rectangles


def _adb_screenrecord_stream(serial: Optional[str] = None, bit_rate: str = "8000000", size: Optional[str] = None):
    if av is None:
        raise RuntimeError("PyAV (av) is required for streaming. Install with: pip install av")
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["exec-out", "screenrecord", "--output-format=h264"]
    if bit_rate:
        cmd += ["--bit-rate", str(bit_rate)]
    if size:
        cmd += ["--size", size]
    cmd += ["-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.stdout is None:
        raise RuntimeError("Failed to capture adb stdout")
    container = av.open(proc.stdout, format="h264")
    return proc, container


def _scrcpy_stream(serial: Optional[str] = None, max_size: int = 0, bit_rate: str = "8000000", output_format: str = "mkv"):
    if av is None:
        raise RuntimeError("PyAV (av) is required for streaming. Install with: pip install av")
    fmt_flag = "matroska" if output_format == "mkv" else output_format
    cmd = [
        "scrcpy",
        "--no-audio",
        "--no-control",
        "--no-display",
        "--bit-rate",
        str(bit_rate),
        "--record",
        "-",
        "--output-format",
        output_format,
    ]
    if max_size and max_size > 0:
        cmd += ["--max-size", str(max_size)]
    if serial:
        cmd += ["--serial", serial]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.stdout is None:
        raise RuntimeError("Failed to capture scrcpy stdout")
    try:
        container = av.open(proc.stdout)
    except Exception:
        container = av.open(proc.stdout, format=fmt_flag)
    return proc, container


class _StreamReader:
    """Background reader that exposes the latest BGR frame."""

    def __init__(self, source: str = "adb", serial: Optional[str] = None, size: Optional[str] = None, bit_rate: str = "8000000"):
        self.source = source
        self.serial = serial
        self.size = size
        self.bit_rate = bit_rate
        self._proc: Optional[subprocess.Popen] = None
        self._container = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._latest: Optional[np.ndarray] = None
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._error: Optional[BaseException] = None

    def start(self) -> None:
        if self._thr is not None:
            return
        if self.source == "adb":
            self._proc, self._container = _adb_screenrecord_stream(serial=self.serial, bit_rate=self.bit_rate, size=self.size)
            self._thr = threading.Thread(target=self._run_av, daemon=True)
        elif self.source == "scrcpy":
            max_size = int(self.size.split("x")[0]) if (self.size and "x" in self.size) else 0
            self._proc, self._container = _scrcpy_stream(serial=self.serial, max_size=max_size, bit_rate=self.bit_rate, output_format="mkv")
            self._thr = threading.Thread(target=self._run_av, daemon=True)
        elif self.source.startswith("video:"):
            path = self.source.split(":", 1)[1]
            self._cap = cv2.VideoCapture(path)
            if not self._cap.isOpened():
                raise RuntimeError(f"Failed to open video source: {path}")
            self._thr = threading.Thread(target=self._run_cv, daemon=True)
        elif self.source.startswith("cam:"):
            idx = int(self.source.split(":", 1)[1])
            self._cap = cv2.VideoCapture(idx)
            if not self._cap.isOpened():
                raise RuntimeError(f"Failed to open camera: {idx}")
            self._thr = threading.Thread(target=self._run_cv, daemon=True)
        else:
            raise ValueError("source must be 'adb', 'scrcpy', 'video:/path', or 'cam:N'")
        self._thr.start()

    def _run_av(self) -> None:
        try:
            assert self._container is not None
            for packet in self._container.demux():
                if self._stop.is_set():
                    break
                for frame in packet.decode():
                    if getattr(frame, "width", 0) <= 0:
                        continue
                    img = frame.to_ndarray(format="bgr24")
                    with self._frame_lock:
                        self._latest = img
                        self._frame_ready.set()
        except BaseException as e:
            self._error = e
        finally:
            self._cleanup()

    def _run_cv(self) -> None:
        try:
            assert self._cap is not None
            while not self._stop.is_set():
                ok, img = self._cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue
                with self._frame_lock:
                    self._latest = img
                    self._frame_ready.set()
        except BaseException as e:
            self._error = e
        finally:
            self._cleanup()

    def get_latest(self, timeout: float = 2.5) -> np.ndarray:
        if self._error:
            raise RuntimeError(f"stream error: {self._error}") from self._error
        if self._latest is None:
            if not self._frame_ready.wait(timeout):
                raise TimeoutError("no stream frames received")
        with self._frame_lock:
            if self._latest is None:
                raise TimeoutError("no stream frames available")
            return self._latest.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._container is not None:
                with contextlib.suppress(Exception):
                    self._container.close()
        except Exception:
            pass
        try:
            if self._proc is not None:
                with contextlib.suppress(Exception):
                    self._proc.terminate()
                with contextlib.suppress(Exception):
                    self._proc.kill()
        except Exception:
            pass
        try:
            if self._cap is not None:
                with contextlib.suppress(Exception):
                    self._cap.release()
        except Exception:
            pass


class StreamBot(Bot):
    """Bot that sources screenshots from a background video stream."""

    def __init__(
        self,
        source: str = "adb",  # 'adb' | 'scrcpy' | 'video:/path' | 'cam:N'
        serial: Optional[str] = None,
        size: Optional[str] = None,  # e.g. "1280x720" for adb; scrcpy uses --max-size (width)
        bit_rate: str = "8000000",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._reader = _StreamReader(source=source, serial=serial, size=size, bit_rate=bit_rate)
        self._reader.start()

    def screenshot(self) -> np.ndarray:  # type: ignore[override]
        return self._reader.get_latest(timeout=5.0)

    def close(self) -> None:
        self._reader.stop()

    def __enter__(self) -> "StreamBot":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- Streaming match utilities ---
    def _match_on_frame(self, frame: np.ndarray, template: np.ndarray, threshold: float = 0.7, gray: bool = False) -> np.ndarray:
        """Return grouped rectangles (Nx4) for matches in the given frame."""
        if gray:
            frame_g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            tpl_g = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template.ndim == 3 else template
            res = cv2.matchTemplate(frame_g, tpl_g, cv2.TM_CCOEFF_NORMED)
            th, tw = tpl_g.shape[:2]
        else:
            res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            th, tw = template.shape[:2]
        loc = np.where(res >= threshold)
        locs = list(zip(*loc[::-1]))
        if not locs:
            return np.empty((0, 4), dtype=np.int32)
        rects = [(int(x), int(y), int(x + tw), int(y + th)) for (x, y) in locs]
        rects2 = rects + rects
        grouped, _ = cv2.groupRectangles(rects2, groupThreshold=1, eps=0.01)
        if grouped is None or len(grouped) == 0:
            grouped = np.array(rects[: self.max_results], dtype=np.int32)
        return grouped

    def stream_match(
        self,
        template_path: str,
        threshold: float = 0.7,
        gray: bool = False,
        gui: bool = False,
    ) -> None:
        """
        Continuously match a template on the live stream.
        - Headless (default): prints first match coords per frame if present.
        - GUI mode: shows a window with overlay and 'q' to quit.
        """
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise RuntimeError(f"Failed to load template: {template_path}")
        win = "stream_match (q=quit)"
        headless = not gui
        if not headless:
            try:
                cv2.namedWindow(win, cv2.WINDOW_NORMAL)
            except Exception:
                headless = True
        try:
            while True:
                frame = self.screenshot()
                rects = self._match_on_frame(frame, template, threshold=threshold, gray=gray)
                if rects.size > 0:
                    x1, y1, x2, y2 = map(int, rects[0].tolist())
                    cx, cy = rect_center([x1, y1, x2, y2])
                    if headless:
                        print(f"match: {x1} {y1} {x2} {y2} center=({cx},{cy})")
                    else:
                        try:
                            frame = draw_rectangles(frame, rects, color=(0, 255, 0), thickness=2)
                            cv2.drawMarker(frame, (cx, cy), (0, 255, 255), markerType=cv2.MARKER_TILTED_CROSS, markerSize=24, thickness=2)
                            cv2.displayStatusBar(win, f"Match @ ({cx},{cy})", 250)
                        except Exception:
                            pass
                if not headless:
                    cv2.imshow(win, frame)
                    if (cv2.waitKey(1) & 0xFF) == ord('q'):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            with contextlib.suppress(Exception):
                cv2.destroyAllWindows()
