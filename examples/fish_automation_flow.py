"""
Example: Streaming fish-catch automation flow.

This example demonstrates advanced game automation using StreamBot:
1) Wait for farmpongfish2 to light up and click it quickly.
2) When incapturefish overlay appears, click the moving catchingfish button until done.

Works with StreamBot on adb or a video source (e.g., scrcpy -> v4l2loopback).

Usage: python examples/fish_automation_flow.py
"""

import time
from typing import Optional, Tuple

import numpy as np

from stream_bot import StreamBot
from bot import rect_center


TPL_FISH_BUTTON = "farmpongfish.png"
TPL_IN_CAPTURE = "incapturefish.png"
TPL_CATCH = "catchingfish.png"
TPL_CAUGHT = "youcaughtsomething.png"  # optional end cue


def clamp_roi(img_shape: Tuple[int, int, int], roi: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    h, w = img_shape[:2]
    x, y, rw, rh = roi
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    rw = max(1, min(rw, w - x))
    rh = max(1, min(rh, h - y))
    return x, y, rw, rh


def run(source: str = "adb", size: Optional[str] = "1280x720", bit_rate: str = "8000000") -> None:
    b = StreamBot(source=source, size=size, bit_rate=bit_rate)
    try:
        state = "SEA"  # SEA -> ENTER_CAPTURE -> CATCHING
        last_click_ts = 0.0
        click_cooldown = 0.1
        idle_sleep = 0.02
        # dynamic ROI near last seen catching button (to speed up)
        catch_roi: Optional[Tuple[int, int, int, int]] = None

        while True:
            now = time.time()
            print("State: " + str(state))
            if state == "SEA":
                # Look for the lit fish button; click immediately on appear
                appeared = b.wait_for_image(TPL_FISH_BUTTON, threshold=0.5, timeout=2.0, click_on_appear=True, use_gray=False)
                if appeared:
                    # Optional extra tap to ensure the click registered (button is brief)
                    time.sleep(0.05)
                    b.tap_image(TPL_FISH_BUTTON, threshold=0.88)
                    state = "ENTER_CAPTURE"
                    continue
                # No button yet; short idle
                time.sleep(idle_sleep)

            elif state == "ENTER_CAPTURE":
                # Wait briefly for capture overlay; fallback to SEA if not seen
                if b.wait_for_image(TPL_IN_CAPTURE, threshold=0.85, timeout=1.5):
                    catch_roi = None
                    state = "CATCHING"
                    continue
                else:
                    state = "SEA"
                    continue

            elif state == "CATCHING":
                # Stop if capture overlay is gone (or optional success banner appears)
                in_cap = b.wait_for_image(TPL_IN_CAPTURE, threshold=0.85, timeout=0.001)
                if not in_cap:
                    state = "SEA"
                    continue

                # Try a fast ROI search first if we have one
                search_roi = None
                if catch_roi is not None:
                    # sanity clamp to current frame dimensions using a quick grab
                    frame = b.screenshot()
                    search_roi = clamp_roi(frame.shape, catch_roi)

                _, rects = b.match_template(
                    TPL_CATCH,
                    threshold=0.7,
                    return_image=False,
                    use_gray=True,
                    search_roi=search_roi,
                )

                if len(rects) == 0 and search_roi is not None:
                    # Fallback to full-frame if ROI missed
                    _, rects = b.match_template(TPL_CATCH, threshold=0.7, return_image=False, use_gray=True)

                if len(rects) > 0:
                    x1, y1, x2, y2 = map(int, rects[0].tolist())
                    cx, cy = rect_center([x1, y1, x2, y2])
                    # Update ROI around the button with margin
                    margin = 160
                    catch_roi = (max(0, x1 - margin), max(0, y1 - margin), (x2 - x1) + 2 * margin, (y2 - y1) + 2 * margin)

                    if now - last_click_ts >= click_cooldown:
                        b.click(cx, cy)
                        last_click_ts = now
                else:
                    # Light idle; button moves quickly
                    time.sleep(0.01)

                # Optional: detect success banner to exit early
                _ok = b.wait_for_image(TPL_CAUGHT, threshold=0.8, timeout=0.001)
                if _ok:
                    state = "SEA"
                    time.sleep(0.2)
                    continue

            else:
                state = "SEA"
                time.sleep(idle_sleep)

    finally:
        b.close()


if __name__ == "__main__":
    # Example: run with adb source
    run(source="adb", size="1280x720")
    # Alternative: run with v4l2 video source
    # run(source="video:/dev/video10")