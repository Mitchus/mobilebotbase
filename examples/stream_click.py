#!/usr/bin/env python3
"""
Stream match + click GUI

Shows the live stream with template overlays. Left-click the window to tap the
current best match center on the phone (ADB). All matching uses streaming frames.

Usage examples:
    python examples/stream_click.py --template img/catchingfish.png --source adb --size 1280x720 --gray --canvas 1920x1080
    python examples/stream_click.py --template img/catchingfish.png --source video:/dev/video10 --gray --canvas 1920x1080
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple, List, Dict

import cv2
import numpy as np

# Ensure repo root is on sys.path when running this file directly
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from stream_bot import StreamBot


def match_template(frame: np.ndarray, template: np.ndarray, threshold: float = 0.7, gray: bool = False) -> np.ndarray:
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
    # group for stability
    rects2 = rects + rects
    grouped, _ = cv2.groupRectangles(rects2, groupThreshold=1, eps=0.01)
    if grouped is None or len(grouped) == 0:
        grouped = np.array(rects[:32], dtype=np.int32)
    return grouped


def rect_center(r: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x1, y1, x2, y2 = map(int, r)
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def _draw_panel(frame: np.ndarray, lines: List[str], origin=(8, 8)) -> None:
    # Draw semi-transparent panel with text lines
    overlay = frame.copy()
    x0, y0 = origin
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.5
    lh = 18
    padding = 6
    w = 0
    for ln in lines:
        size, _ = cv2.getTextSize(ln, font, fs, 1)
        w = max(w, size[0])
    h = lh * len(lines)
    cv2.rectangle(overlay, (x0 - padding, y0 - padding), (x0 + w + padding, y0 + h + padding), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    y = y0 + lh - 4
    for ln in lines:
        cv2.putText(frame, ln, (x0, y), font, fs, (255, 255, 255), 1, cv2.LINE_AA)
        y += lh


def _draw_buttons(frame: np.ndarray, labels: List[str], origin=(8, 110)) -> List[Tuple[int, int, int, int]]:
    # Draw clickable buttons; return list of rects (x,y,w,h) in frame coords
    x, y = origin
    rects: List[Tuple[int, int, int, int]] = []
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.5
    padx, pady = 10, 6
    gap = 6
    for label in labels:
        size, _ = cv2.getTextSize(label, font, fs, 1)
        w = size[0] + 2 * padx
        h = size[1] + 2 * pady
        cv2.rectangle(frame, (x, y), (x + w, y + h), (30, 30, 30), -1)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (180, 180, 180), 1)
        cv2.putText(frame, label, (x + padx, y + h - pady - 2), font, fs, (255, 255, 255), 1, cv2.LINE_AA)
        rects.append((x, y, w, h))
        x += w + gap
    return rects


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Stream template match with click-through")
    ap.add_argument("--template", required=True, help="Path to template image (e.g., img/catchingfish.png)")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--gray", action="store_true")
    ap.add_argument("--source", default="adb", help="adb | scrcpy | video:/path | cam:N")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--bit-rate", default="8000000")
    ap.add_argument("--scale", type=float, default=1.0, help="Display scale factor for the window (ignored if --canvas is used)")
    ap.add_argument("--canvas", type=str, default="1920x1080", help="Composite canvas WxH (stream left quarter, GUI right)")
    args = ap.parse_args(argv)

    tpl_path = args.template
    if not (tpl_path.startswith("/") or tpl_path.startswith("img/")):
        tpl_path = os.path.join("img", tpl_path)

    tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
    if tpl is None:
        print(f"Failed to load template: {tpl_path}", file=sys.stderr)
        return 2

    bot = StreamBot(source=args.source, serial=args.serial, size=args.size, bit_rate=args.bit_rate)

    win = "stream_click (q=quit, left-click=ADB tap @ best match)"
    try:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    except Exception:
        print("OpenCV GUI unavailable. Run headless or install GUI-capable OpenCV.", file=sys.stderr)
        return 2

    latest_center: Optional[Tuple[int, int]] = None
    latest_rect: Optional[Tuple[int, int, int, int]] = None
    # Parse canvas WxH and compute layout: stream on left quarter, GUI on right area
    try:
        cw, ch = [int(v) for v in str(args.canvas).lower().split("x", 1)]
    except Exception:
        cw, ch = 1920, 1080
    cw = max(640, cw)
    ch = max(480, ch)
    stream_area_w = max(200, cw // 4)
    stream_area_h = ch
    panel_x0 = stream_area_w
    panel_w = cw - stream_area_w
    panel_h = ch
    scale = 1.0  # we render into a fixed canvas
    auto_click = False
    roi_lock = False
    roi_rect: Optional[Tuple[int, int, int, int]] = None  # in frame coords
    click_cooldown = 0.12
    last_click_ts = 0.0
    show_help = True

    # Template management state
    def list_templates(img_dir: str = "img") -> List[str]:
        try:
            names = [f for f in os.listdir(img_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        except FileNotFoundError:
            names = []
        names.sort()
        return [os.path.join(img_dir, n) for n in names]

    tpl_list: List[str] = list_templates()
    # Ensure current template is part of the list (if custom path)
    if tpl_path not in tpl_list:
        tpl_list = [tpl_path] + tpl_list
    tpl_index = max(0, tpl_list.index(tpl_path) if tpl_path in tpl_list else 0)

    def load_template_at(idx: int) -> None:
        nonlocal tpl, tpl_path, tpl_index
        if not tpl_list:
            return
        tpl_index = idx % len(tpl_list)
        path = tpl_list[tpl_index]
        t = cv2.imread(path, cv2.IMREAD_COLOR)
        if t is None:
            print(f"Failed to load template: {path}", file=sys.stderr)
            return
        tpl = t
        tpl_path = path
        print(f"Loaded template: {os.path.basename(tpl_path)}")

    def refresh_templates() -> None:
        nonlocal tpl_list
        tpl_list = list_templates()
        if tpl_path not in tpl_list and os.path.exists(tpl_path):
            tpl_list = [tpl_path] + tpl_list

    # UI geometry caches and interaction state
    btn_rects_canvas: List[Tuple[int, int, int, int]] = []  # row 1 buttons (Click/Auto/ROI)
    btn_rects_row2: List[Tuple[int, int, int, int]] = []     # row 2 buttons (Prev/Next/Reload)
    btn_rects_row3: List[Tuple[int, int, int, int]] = []     # row 3 buttons (Draw ROI/Clear ROI/New Tpl)
    list_item_rects: List[Tuple[int, int, int, int]] = []    # template list clickable rows

    # Drawing/selection modes
    draw_mode: Optional[str] = None  # None | 'roi' | 'tpl'
    dragging: bool = False
    drag_start_frame: Optional[Tuple[int, int]] = None
    drag_end_frame: Optional[Tuple[int, int]] = None
    last_frame: Optional[np.ndarray] = None  # latest BGR frame for saving crops

    # Canvas->frame mapping updated each frame
    last_map: Dict[str, int | float] = {"s": 1.0, "x0": 0, "y0": 0, "stream_w": stream_area_w, "stream_h": stream_area_h, "fw": 0, "fh": 0}

    def on_mouse(event, x, y, flags, param):  # noqa: ARG001
        nonlocal latest_center, auto_click, roi_lock, draw_mode, dragging, drag_start_frame, drag_end_frame, roi_rect
        # Panel or stream region?
        in_panel = x >= panel_x0

        # Map canvas -> frame coords for stream region
        s = float(last_map.get("s", 1.0))
        x0 = int(last_map.get("x0", 0))
        y0 = int(last_map.get("y0", 0))
        fw = int(last_map.get("fw", 0))
        fh = int(last_map.get("fh", 0))

        def to_frame(cx: int, cy: int) -> Optional[Tuple[int, int]]:
            if not (x0 <= cx < x0 + int(last_map.get("stream_w", 0)) and y0 <= cy < y0 + int(last_map.get("stream_h", 0))):
                return None
            fx = int((cx - x0) / max(1e-6, s))
            fy = int((cy - y0) / max(1e-6, s))
            if 0 <= fx < fw and 0 <= fy < fh:
                return fx, fy
            return None

        # Handle button clicks in panel
        if event == cv2.EVENT_LBUTTONDOWN and in_panel:
            # Row 1 buttons
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_canvas):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Click
                        if latest_center is not None:
                            cx, cy = latest_center
                            bot.click(int(cx), int(cy))
                            print(f"tap: {cx} {cy}")
                    elif idx == 1:  # Auto
                        auto_click = not auto_click
                        print(f"auto_click: {auto_click}")
                    elif idx == 2:  # ROI lock toggle
                        roi_lock = not roi_lock
                        print(f"roi_lock: {roi_lock}")
                    return
            # Row 2 buttons: Prev/Next/Reload
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_row2):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Prev
                        if tpl_list:
                            load_template_at((tpl_index - 1) % len(tpl_list))
                    elif idx == 1:  # Next
                        if tpl_list:
                            load_template_at((tpl_index + 1) % len(tpl_list))
                    elif idx == 2:  # Reload
                        refresh_templates()
                        print("Templates reloaded")
                    return
            # Row 3 buttons: Draw ROI / Clear ROI / New Template
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_row3):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Draw ROI toggle
                        draw_mode = None if draw_mode == 'roi' else 'roi'
                        dragging = False
                        print(f"draw_mode: {draw_mode}")
                    elif idx == 1:  # Clear ROI
                        roi_lock = False
                        roi_rect = None
                        print("ROI cleared")
                    elif idx == 2:  # New Template from ROI (enter draw mode)
                        draw_mode = None if draw_mode == 'tpl' else 'tpl'
                        dragging = False
                        print(f"draw_mode: {draw_mode}")
                    return
            # Template list clicks
            for idx, (bx, by, bw, bh) in enumerate(list_item_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx < len(tpl_list):
                        load_template_at(idx)
                    return
            return

        # Stream interactions (left area)
        if draw_mode in ('roi', 'tpl'):
            if event == cv2.EVENT_LBUTTONDOWN:
                pt = to_frame(x, y)
                if pt is not None:
                    dragging = True
                    drag_start_frame = pt
                    drag_end_frame = pt
            elif event == cv2.EVENT_MOUSEMOVE and dragging and (flags & cv2.EVENT_FLAG_LBUTTON):
                pt = to_frame(x, y)
                if pt is not None:
                    drag_end_frame = pt
            elif event == cv2.EVENT_LBUTTONUP and dragging:
                dragging = False
                pt = to_frame(x, y)
                if pt is not None:
                    drag_end_frame = pt
                # finalize rectangle
                if drag_start_frame and drag_end_frame and last_frame is not None:
                    x1, y1 = drag_start_frame
                    x2, y2 = drag_end_frame
                    xx1, yy1 = max(0, min(x1, x2)), max(0, min(y1, y2))
                    xx2, yy2 = min(fw - 1, max(x1, x2)), min(fh - 1, max(y1, y2))
                    w, h = max(0, xx2 - xx1), max(0, yy2 - yy1)
                    if w >= 5 and h >= 5:
                        if draw_mode == 'roi':
                            roi_rect = (xx1, yy1, w, h)
                            roi_lock = True
                            print(f"ROI set: {roi_rect}")
                        elif draw_mode == 'tpl':
                            crop = last_frame[yy1:yy1 + h, xx1:xx1 + w].copy()
                            os.makedirs('img', exist_ok=True)
                            ts = time.strftime('%Y%m%d_%H%M%S')
                            out = os.path.join('img', f'tpl_{w}x{h}_{ts}.png')
                            cv2.imwrite(out, crop)
                            print(f"Saved new template: {out}")
                            refresh_templates()
                            # load this new template
                            if out in tpl_list:
                                load_template_at(tpl_list.index(out))
                            else:
                                # prepend and select
                                tpl_list.insert(0, out)
                                load_template_at(0)
                    else:
                        print("Drawn region too small; ignored")
                draw_mode = None
                drag_start_frame = None
                drag_end_frame = None
            return

        # Default: left-click taps current match center
        if event == cv2.EVENT_LBUTTONDOWN and not in_panel:
            if latest_center is not None:
                cx, cy = latest_center
                bot.click(int(cx), int(cy))
                print(f"tap: {cx} {cy}")

    cv2.setMouseCallback(win, on_mouse)

    prev_time = time.time()
    fps_smooth = 0.0

    try:
        while True:
            frame = bot.screenshot()  # stream frame (BGR)
            last_frame = frame
            # Optional ROI search for speed
            search_rect = roi_rect if (roi_lock and roi_rect is not None) else None
            if search_rect is not None:
                x, y, w, h = search_rect
                x = max(0, x); y = max(0, y); w = max(1, w); h = max(1, h)
                x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
                crop = frame[y:y2, x:x2]
                rects = match_template(crop, tpl, threshold=args.threshold, gray=args.gray)
                # map back to full-frame coords
                if rects.size > 0:
                    rects[:, [0, 2]] += x
                    rects[:, [1, 3]] += y
            else:
                rects = match_template(frame, tpl, threshold=args.threshold, gray=args.gray)
            if rects.size > 0:
                x1, y1, x2, y2 = map(int, rects[0].tolist())
                cx, cy = rect_center((x1, y1, x2, y2))
                latest_center = (cx, cy)
                latest_rect = (x1, y1, x2, y2)
                # overlay
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.drawMarker(frame, (cx, cy), (0, 255, 255), markerType=cv2.MARKER_TILTED_CROSS, markerSize=24, thickness=2)
                status = f"match @ ({cx},{cy}) thr={args.threshold:.2f} {'ROI' if roi_lock else ''}"
                # update ROI around the match
                margin = 160
                rx = max(0, x1 - margin)
                ry = max(0, y1 - margin)
                rw = min(frame.shape[1] - rx, (x2 - x1) + 2 * margin)
                rh = min(frame.shape[0] - ry, (y2 - y1) + 2 * margin)
                roi_rect = (rx, ry, rw, rh)
                # auto-click if enabled
                if auto_click:
                    now = time.time()
                    if now - last_click_ts >= click_cooldown:
                        bot.click(int(cx), int(cy))
                        last_click_ts = now
            else:
                latest_center = None
                latest_rect = None
                status = "no match"

            # FPS
            now = time.time()
            dt = max(1e-6, now - prev_time)
            prev_time = now
            fps = 1.0 / dt
            fps_smooth = 0.9 * fps_smooth + 0.1 * fps if fps_smooth > 0 else fps
            # Compose canvas with stream on left and GUI panel on right
            fh, fw = frame.shape[:2]
            s = min(stream_area_w / max(1, fw), stream_area_h / max(1, fh))
            rw, rh = max(1, int(fw * s)), max(1, int(fh * s))
            # place stream centered within left area
            canvas = np.zeros((ch, cw, 3), dtype=np.uint8)
            x0 = (stream_area_w - rw) // 2
            y0 = (stream_area_h - rh) // 2
            disp_stream = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_AREA)
            # If dragging a rectangle, draw it on a copy of frame before resizing
            if draw_mode in ('roi', 'tpl') and drag_start_frame and drag_end_frame:
                xs, ys = drag_start_frame
                xe, ye = drag_end_frame
                xx1, yy1 = max(0, min(xs, xe)), max(0, min(ys, ye))
                xx2, yy2 = min(fw - 1, max(xs, xe)), min(fh - 1, max(ys, ye))
                overlay = frame.copy()
                cv2.rectangle(overlay, (xx1, yy1), (xx2, yy2), (255, 0, 255), 2)
                disp_stream = cv2.resize(overlay, (rw, rh), interpolation=cv2.INTER_AREA)
            canvas[y0:y0+rh, x0:x0+rw] = disp_stream

            # Update mapping for mouse callback
            last_map.update({"s": s, "x0": x0, "y0": y0, "fw": fw, "fh": fh, "stream_w": stream_area_w, "stream_h": stream_area_h})

            # Draw panel contents on the right side
            panel_origin_x = panel_x0 + 16
            panel_origin_y = 16
            # Title
            cv2.putText(canvas, os.path.basename(tpl_path), (panel_origin_x, panel_origin_y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200,200,200), 2, cv2.LINE_AA)
            # Keymap
            if show_help:
                _draw_panel(canvas, [
                    f"[Click] tap best match",
                    f"[Auto ] auto-click: {'ON' if auto_click else 'OFF'}",
                    f"[ROI  ] ROI lock: {'ON' if roi_lock else 'OFF'}",
                    f"Keys: c=auto  r=roi  g=gray  +/-=thr  s=snap  q=quit",
                    f"thr={args.threshold:.2f} gray={args.gray}",
                ], origin=(panel_origin_x, panel_origin_y + 24))
            # Buttons row 1 (canvas coords)
            btn_rects_canvas = _draw_buttons(canvas, ["Click", f"Auto:{'ON' if auto_click else 'OFF'}", f"ROI:{'ON' if roi_lock else 'OFF'}"], origin=(panel_origin_x, panel_origin_y + 140))

            # Buttons row 2: template navigation
            btn_rects_row2 = _draw_buttons(canvas, ["Prev Tpl", "Next Tpl", "Reload"], origin=(panel_origin_x, panel_origin_y + 180))

            # Buttons row 3: ROI and template creation
            lbl_roi = "Cancel Draw" if draw_mode == 'roi' else "Draw ROI"
            lbl_tpl = "Cancel New" if draw_mode == 'tpl' else "New Tpl (ROI)"
            btn_rects_row3 = _draw_buttons(canvas, [lbl_roi, "Clear ROI", lbl_tpl], origin=(panel_origin_x, panel_origin_y + 220))

            # Template list
            list_item_rects = []
            list_x = panel_origin_x
            list_y = panel_origin_y + 270
            item_h = 24
            max_items = max(5, (ch - list_y - 60) // item_h)
            font = cv2.FONT_HERSHEY_SIMPLEX
            fs = 0.5
            shown = min(max_items, len(tpl_list))
            for i in range(shown):
                name = os.path.basename(tpl_list[i])
                y1 = list_y + i * item_h
                y2 = y1 + item_h - 4
                x1 = list_x
                x2 = panel_x0 + panel_w - 16
                # background highlight
                bg = (40, 40, 40) if i != tpl_index else (70, 70, 90)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), bg, -1)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (90, 90, 90), 1)
                cv2.putText(canvas, name[:48], (x1 + 8, y1 + item_h - 8), font, fs, (230, 230, 230), 1, cv2.LINE_AA)
                list_item_rects.append((x1, y1, x2 - x1, y2 - y1))

            # FPS/status on bottom of panel
            status_text = status + f" | {fps_smooth:.1f} FPS"
            cv2.putText(canvas, status_text, (panel_origin_x, ch - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180,180,180), 2, cv2.LINE_AA)

            # Show composite canvas
            cv2.imshow(win, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key in (ord('+'), ord('=')):
                args.threshold = min(0.99, args.threshold + 0.02)
            elif key == ord('-'):
                args.threshold = max(0.01, args.threshold - 0.02)
            elif key == ord('g'):
                args.gray = not args.gray
            elif key == ord('c'):
                auto_click = not auto_click
            elif key == ord('r'):
                roi_lock = not roi_lock
            elif key == ord('s'):
                os.makedirs('img', exist_ok=True)
                ts = time.strftime('%Y%m%d_%H%M%S')
                out = os.path.join('img', f'stream_{ts}.png')
                cv2.imwrite(out, frame)
                print(f"saved {out}")
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyWindow(win)
        bot.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
