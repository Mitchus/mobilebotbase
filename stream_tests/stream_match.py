#!/usr/bin/env python3
"""
Live stream template matching demo.

- Default: reads H.264 video from adb exec-out screenrecord
- Fallback: use a local video file or webcam (OpenCV VideoCapture)

Headless by default (prints match coordinates). Use --gui to display a window.
Press q to quit when GUI is enabled.
"""
from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Optional, Tuple
import contextlib

import numpy as np
import cv2

try:
    import av  # PyAV
except Exception:
    av = None  # type: ignore


def draw_marker(img: np.ndarray, cx: int, cy: int, color=(0, 255, 255)) -> None:
    cv2.drawMarker(img, (int(cx), int(cy)), color, markerType=cv2.MARKER_TILTED_CROSS, markerSize=24, thickness=2)


def rect_center(r: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x1, y1, x2, y2 = map(int, r)
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def match_template(frame: np.ndarray, template: np.ndarray, threshold: float = 0.7, gray: bool = False):
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
        return []
    rects = [(int(x), int(y), int(x + tw), int(y + th)) for (x, y) in locs]
    rects2 = rects + rects
    grouped, _ = cv2.groupRectangles(rects2, groupThreshold=1, eps=0.01)
    if grouped is None or len(grouped) == 0:
        grouped = np.array(rects[:32], dtype=np.int32)
    return grouped.tolist()


def adb_screenrecord_stream(serial: Optional[str] = None, bit_rate: str = "8000000", size: Optional[str] = None):
    """Start adb exec-out screenrecord and return (proc, av_container)."""
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
    print("Starting adb screenrecord stream:", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.stdout is None:
        raise RuntimeError("Failed to capture adb stdout")
    container = av.open(proc.stdout, format="h264")
    return proc, container


def scrcpy_stream(serial: Optional[str] = None, max_size: int = 0, bit_rate: str = "8000000", output_format: str = "mkv"):
    """Start scrcpy and stream recorded video to stdout, returning (proc, av_container).

    output_format: 'mkv' or 'mp4'. 'mkv' is preferred for streaming.
    """
    if av is None:
        raise RuntimeError("PyAV (av) is required for streaming. Install with: pip install av")
    fmt_flag = "matroska" if output_format == "mkv" else output_format
    cmd = [
        "scrcpy",
        "--no-audio",
        "--no-control",
        "--no-display",
        "--bit-rate", str(bit_rate),
        "--record", "-",
        "--output-format", output_format,
    ]
    if max_size and max_size > 0:
        cmd += ["--max-size", str(max_size)]
    if serial:
        cmd += ["--serial", serial]
    print("Starting scrcpy stream:", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.stdout is None:
        raise RuntimeError("Failed to capture scrcpy stdout")
    # Open container from stdout pipe; specify format for robustness
    container = None
    try:
        container = av.open(proc.stdout)
    except Exception:
        container = av.open(proc.stdout, format=fmt_flag)
    return proc, container


def opencv_capture(source: str):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video source: {source}")
    return cap


def main():
    ap = argparse.ArgumentParser(description="Live stream template matcher")
    ap.add_argument("--template", required=True, help="Path to template image (e.g., img/catchingfish.png)")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--gray", action="store_true", help="Use grayscale matching for speed")
    ap.add_argument("--source", default="adb", help="adb (default), scrcpy, or video:/path or cam:0")
    ap.add_argument("--serial", type=str, default=None, help="adb device serial")
    ap.add_argument("--size", type=str, default=None, help="adb: WIDTHxHEIGHT for screenrecord (e.g., 1280x720)")
    ap.add_argument("--bit-rate", type=str, default="8000000", help="adb/screenrecord bitrate (e.g., 8000000 for 8Mbps)")
    ap.add_argument("--gui", action="store_true", help="Show a window with overlay; otherwise print matches (headless)")
    args = ap.parse_args()

    tpl = cv2.imread(args.template, cv2.IMREAD_COLOR)
    if tpl is None:
        print(f"Failed to load template: {args.template}")
        sys.exit(2)

    use_adb = args.source == "adb"
    use_scrcpy = args.source == "scrcpy"
    proc = None

    try:
        if use_adb:
            if av is None:
                print("PyAV is not installed. Use --source video:<file> or pip install av")
                sys.exit(2)
            proc, container = adb_screenrecord_stream(serial=args.serial, bit_rate=args.bit_rate, size=args.size)
            win = "stream_match (q=quit)"
            headless = not args.gui
            if not headless:
                try:
                    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                except Exception:
                    print("GUI unavailable; falling back to headless printing.")
                    headless = True
            for packet in container.demux():
                for frame in packet.decode():
                    if frame is None or frame.width == 0:
                        continue
                    img = frame.to_ndarray(format="bgr24")
                    rects = match_template(img, tpl, threshold=args.threshold, gray=args.gray)
                    if rects:
                        x1, y1, x2, y2 = rects[0]
                        cx, cy = rect_center((x1, y1, x2, y2))
                        if not headless:
                            draw_marker(img, cx, cy)
                            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            with contextlib.suppress(Exception):
                                cv2.displayStatusBar(win, f"Match @ ({cx},{cy})", 500)
                        else:
                            print(f"match: {x1} {y1} {x2} {y2} center=({cx},{cy})")
                    if not headless:
                        cv2.imshow(win, img)
                        if (cv2.waitKey(1) & 0xFF) == ord('q'):
                            raise KeyboardInterrupt()
        elif use_scrcpy:
            if av is None:
                print("PyAV is not installed. Use --source video:<file> or pip install av")
                sys.exit(2)
            max_size = int(args.size.split('x')[0]) if args.size and 'x' in args.size else 0
            try:
                proc, container = scrcpy_stream(serial=args.serial, max_size=max_size, bit_rate=args.bit_rate, output_format="mkv")
            except Exception as e:
                print("Failed to read scrcpy stream from stdout (record pipe).")
                print("Tip: Use scrcpy with a v4l2 loopback sink and open that device instead:")
                print("  sudo modprobe v4l2loopback devices=1 video_nr=10 card_label='scrcpy' exclusive_caps=1")
                print("  scrcpy --no-audio --no-control --no-display --bit-rate", args.bit_rate, "--v4l2-sink=/dev/video10")
                print("Then run this script with: --source video:/dev/video10")
                sys.exit(2)
            win = "stream_match (q=quit)"
            headless = not args.gui
            if not headless:
                try:
                    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                except Exception:
                    print("GUI unavailable; falling back to headless printing.")
                    headless = True
            for packet in container.demux():
                for frame in packet.decode():
                    # Some containers include non-video packets; filter by type when available
                    if frame is None or getattr(frame, 'width', 0) == 0:
                        continue
                    img = frame.to_ndarray(format="bgr24")
                    rects = match_template(img, tpl, threshold=args.threshold, gray=args.gray)
                    if rects:
                        x1, y1, x2, y2 = rects[0]
                        cx, cy = rect_center((x1, y1, x2, y2))
                        if not headless:
                            draw_marker(img, cx, cy)
                            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            with contextlib.suppress(Exception):
                                cv2.displayStatusBar(win, f"Match @ ({cx},{cy})", 500)
                        else:
                            print(f"match: {x1} {y1} {x2} {y2} center=({cx},{cy})")
                    if not headless:
                        cv2.imshow(win, img)
                        if (cv2.waitKey(1) & 0xFF) == ord('q'):
                            raise KeyboardInterrupt()
        else:
            source = args.source
            if source.startswith("video:"):
                path = source.split(":", 1)[1]
                cap = opencv_capture(path)
            elif source.startswith("cam:"):
                idx = int(source.split(":", 1)[1])
                cap = opencv_capture(idx)
            else:
                print("Invalid --source. Use scrcpy, video:<file>, or cam:<index>.")
                sys.exit(2)

            win = "stream_match (q=quit)"
            headless = not args.gui
            if not headless:
                try:
                    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                except Exception:
                    print("GUI unavailable; falling back to headless printing.")
                    headless = True
            while True:
                ok, img = cap.read()
                if not ok:
                    break
                rects = match_template(img, tpl, threshold=args.threshold, gray=args.gray)
                if rects:
                    x1, y1, x2, y2 = rects[0]
                    cx, cy = rect_center((x1, y1, x2, y2))
                    if not headless:
                        draw_marker(img, cx, cy)
                        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        with contextlib.suppress(Exception):
                            cv2.displayStatusBar(win, f"Match @ ({cx},{cy})", 500)
                    else:
                        print(f"match: {x1} {y1} {x2} {y2} center=({cx},{cy})")
                if not headless:
                    cv2.imshow(win, img)
                    if (cv2.waitKey(1) & 0xFF) == ord('q'):
                        break

    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            cv2.destroyAllWindows()
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.send_signal(signal.SIGINT)
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                proc.kill()


if __name__ == "__main__":
    main()
