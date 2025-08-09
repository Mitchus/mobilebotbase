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
import threading
import importlib.util
import inspect
import uuid

import cv2
import numpy as np

# Ensure repo root is on sys.path when running this file directly
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from stream_bot import StreamBot


def match_template(frame: np.ndarray, template: np.ndarray, threshold: float = 0.7, gray: bool = False) -> np.ndarray:
    # Ensure search area is at least as large as the template
    fh, fw = frame.shape[:2]
    th0, tw0 = template.shape[:2]
    if fh < th0 or fw < tw0:
        return np.empty((0, 4), dtype=np.int32)

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

    # Script management state
    def list_scripts() -> List[str]:
        files: List[str] = []
        # examples/*.py
        ex_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        ex_dir = os.path.abspath(ex_dir)
        if os.path.isdir(ex_dir):
            for f in sorted(os.listdir(ex_dir)):
                if f.endswith(".py") and not f.startswith("_"):
                    files.append(os.path.join(ex_dir, f))
        # repo root .py
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for f in sorted(os.listdir(root)):
            if f.endswith('.py') and f not in (os.path.basename(__file__),):
                files.append(os.path.join(root, f))
        return files

    class ScriptContext:
        def __init__(self):
            self._stop = threading.Event()
        def stop(self):
            self._stop.set()
        def stopped(self) -> bool:
            return self._stop.is_set()
        def sleep(self, secs: float):
            # Cooperative sleep; wake early if stopped
            end = time.time() + max(0.0, secs)
            while not self._stop.is_set() and time.time() < end:
                time.sleep(0.05)

    script_list: List[str] = list_scripts()
    script_index: int = 0 if script_list else -1
    script_thread: Optional[threading.Thread] = None
    script_ctx: Optional[ScriptContext] = None
    script_running: bool = False
    script_status: str = ""

    def run_script_by_index(idx: int):
        nonlocal script_thread, script_ctx, script_running, script_status, script_index
        if not script_list:
            script_status = "No scripts"
            return
        script_index = idx % len(script_list)
        path = script_list[script_index]
        if script_running:
            script_status = "Script already running"
            return
        ctx = ScriptContext()
        script_ctx = ctx

        def _target():
            nonlocal script_running, script_status
            script_running = True
            script_status = f"Running {os.path.basename(path)}"
            try:
                mod_name = f"user_script_{uuid.uuid4().hex}"
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is None or spec.loader is None:
                    raise RuntimeError("Failed to load script spec")
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                # pick a callable: run, main, or flow
                func = None
                for name in ("run", "main", "flow"):
                    f = getattr(mod, name, None)
                    if callable(f):
                        func = f
                        break
                if func is None:
                    raise RuntimeError("No callable run/main/flow found")
                # try to pass (bot, ctx) if supported, else (bot), else ()
                sig = inspect.signature(func)
                if len(sig.parameters) >= 2:
                    func(bot, ctx)
                elif len(sig.parameters) == 1:
                    func(bot)
                else:
                    func()
                script_status = f"Finished {os.path.basename(path)}"
            except Exception as e:
                script_status = f"Error: {e}"
            finally:
                script_running = False

        t = threading.Thread(target=_target, daemon=True)
        script_thread = t
        t.start()

    def stop_script():
        nonlocal script_ctx, script_status
        if script_ctx is not None:
            script_ctx.stop()
            script_status = "Stopping..."

    def refresh_scripts():
        nonlocal script_list
        script_list = list_scripts()
        if script_index >= len(script_list):
            pass

    # ----- Sequence execution helpers -----
    def render_step_label(step: Dict) -> str:
        t = step.get("type")
        if t == "FIND_CLICK_ONE":
            return f"Find+Click: {os.path.basename(step.get('tpl',''))} thr={step.get('threshold',0.7):.2f}"
        if t == "FIND_CLICK_ANY":
            names = ",".join(os.path.basename(p) for p in step.get("tpls", [])[:3])
            more = "…" if len(step.get("tpls", [])) > 3 else ""
            return f"FindAny+Click: [{names}{more}] thr={step.get('threshold',0.7):.2f}"
        if t == "WAIT":
            return f"Wait {step.get('ms',0)} ms"
        if t == "LOOP":
            return f"Loop -> {step.get('to',0)}"
        return str(step)

    def _wait_or_stop(evt: threading.Event, ms: int) -> bool:
        end = time.time() + ms/1000.0
        while time.time() < end:
            if evt.is_set():
                return False
            time.sleep(0.05)
        return True

    def find_and_click_one(frame: np.ndarray, template_path: str, thr: float, gray: bool, roi: Optional[Tuple[int,int,int,int]]) -> Optional[Tuple[int,int]]:
        img = frame
        x_off = 0
        y_off = 0
        if roi is not None:
            x, y, w, h = roi
            x = max(0, x); y = max(0, y); w = max(1, w); h = max(1, h)
            x2, y2 = min(img.shape[1], x + w), min(img.shape[0], y + h)
            img = img[y:y2, x:x2]
            x_off, y_off = x, y
        tpl_img = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if tpl_img is None:
            return None
        rects = match_template(img, tpl_img, threshold=thr, gray=gray)
        if rects.size == 0:
            return None
        x1, y1, x2, y2 = map(int, rects[0].tolist())
        cx, cy = rect_center((x1, y1, x2, y2))
        return (cx + x_off, cy + y_off)

    def find_and_click_any(frame: np.ndarray, templates: List[str], thr: float, gray: bool, roi: Optional[Tuple[int,int,int,int]]) -> Optional[Tuple[int,int]]:
        for p in templates:
            res = find_and_click_one(frame, p, thr, gray, roi)
            if res is not None:
                return res
        return None

    def start_sequence():
        nonlocal seq_thread, seq_running, seq_status, seq_stop
        if seq_running or not seq_steps:
            seq_status = "No sequence or already running"
            return
        stop_evt = threading.Event()
        seq_stop = stop_evt
        def _runner():
            nonlocal seq_running, seq_status
            seq_running = True
            seq_status = "Sequence running"
            i = 0
            try:
                while 0 <= i < len(seq_steps):
                    if stop_evt.is_set():
                        seq_status = "Sequence stopped"
                        break
                    step = seq_steps[i]
                    t = step.get("type")
                    if t == "WAIT":
                        if not _wait_or_stop(stop_evt, int(step.get("ms", 500))):
                            break
                        i += 1
                        continue
                    # get a fresh frame
                    frame_local = bot.screenshot()
                    roi = roi_rect if roi_lock and roi_rect is not None else None
                    if t == "FIND_CLICK_ONE":
                        pos = find_and_click_one(frame_local, step.get("tpl", ""), float(step.get("threshold", args.threshold)), args.gray, roi)
                        if pos is not None:
                            x, y = pos
                            bot.click(int(x), int(y))
                        i += 1
                    elif t == "FIND_CLICK_ANY":
                        pos = find_and_click_any(frame_local, step.get("tpls", []), float(step.get("threshold", args.threshold)), args.gray, roi)
                        if pos is not None:
                            x, y = pos
                            bot.click(int(x), int(y))
                        i += 1
                    elif t == "LOOP":
                        i = int(step.get("to", 0))
                    else:
                        i += 1
                if not stop_evt.is_set():
                    seq_status = "Sequence finished"
            except Exception as e:
                seq_status = f"Seq error: {e}"
            finally:
                seq_running = False
        th = threading.Thread(target=_runner, daemon=True)
        seq_thread = th
        th.start()

    def stop_sequence():
        nonlocal seq_stop, seq_status
        if seq_stop is not None:
            seq_stop.set()
            seq_status = "Sequence stopping..."

    # UI geometry caches and interaction state
    btn_rects_canvas: List[Tuple[int, int, int, int]] = []  # row 1 buttons (Click/Auto/ROI)
    btn_rects_row2: List[Tuple[int, int, int, int]] = []     # row 2 buttons (Prev/Next/Reload)
    btn_rects_row3: List[Tuple[int, int, int, int]] = []     # row 3 buttons (Draw ROI/Clear ROI/New Tpl)
    list_item_rects: List[Tuple[int, int, int, int]] = []    # template list clickable rows (unused if grid)
    tpl_tile_rects: List[Tuple[int, int, int, int]] = []     # template grid tiles
    btn_rects_scripts: List[Tuple[int, int, int, int]] = []  # script control buttons
    script_item_rects: List[Tuple[int, int, int, int]] = []  # script list items
    # Template multi-selection for sequence FindAny
    selected_tpls: set[str] = set()

    # Sequence builder state
    seq_steps: List[Dict] = []
    seq_selected: Optional[int] = None
    seq_thread: Optional[threading.Thread] = None
    seq_running: bool = False
    seq_status: str = ""
    seq_stop: Optional[threading.Event] = None
    btn_rects_seq1: List[Tuple[int, int, int, int]] = []  # Add One / Add Any / Add Wait / Loop->0
    btn_rects_seq2: List[Tuple[int, int, int, int]] = []  # Run / Stop / Clear / Up / Down / Del
    btn_rects_seq_rec: List[Tuple[int, int, int, int]] = []  # REC toggle
    seq_item_rects: List[Tuple[int, int, int, int]] = []
    rec_mode: bool = False

    # Resizable panels state
    v_split_x: int = stream_area_w  # vertical splitter (stream | panel)
    drag_vsplit: bool = False
    hsplit1_ratio: float = 0.34  # templates/scripts split within right panel
    hsplit2_ratio: float = 0.67  # scripts/sequence split within right panel
    drag_hsplit: Optional[int] = None  # 1 or 2
    ui_lines: Dict[str, int] = {"hs1_y": 0, "hs2_y": 0, "panel_x0": panel_x0, "sec_top": 0, "sec_bottom": 0}
    # Side-by-side mode for Scripts and Sequence with a column splitter
    side_by_side: bool = True
    col_split_ratio: float = 0.5  # 0..1; width fraction for left column (Scripts by default)
    drag_colsplit: bool = False

    # Drawing/selection modes
    draw_mode: Optional[str] = None  # None | 'roi' | 'tpl'
    dragging: bool = False
    drag_start_frame: Optional[Tuple[int, int]] = None
    drag_end_frame: Optional[Tuple[int, int]] = None
    last_frame: Optional[np.ndarray] = None  # latest BGR frame for saving crops

    # Canvas->frame mapping updated each frame
    last_map: Dict[str, int | float] = {"s": 1.0, "x0": 0, "y0": 0, "stream_w": stream_area_w, "stream_h": stream_area_h, "fw": 0, "fh": 0}

    def on_mouse(event, x, y, flags, param):  # noqa: ARG001
        nonlocal latest_center, auto_click, roi_lock, draw_mode, dragging, drag_start_frame, drag_end_frame, roi_rect, tpl_index, script_index, seq_selected, rec_mode, v_split_x, drag_vsplit, hsplit1_ratio, hsplit2_ratio, drag_hsplit
        # Panel or stream region?
        panel_x0_local = ui_lines.get("panel_x0", panel_x0)
        in_panel = x >= panel_x0_local

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

        # Vertical splitter drag (between stream and panel)
        if event == cv2.EVENT_LBUTTONDOWN and abs(x - panel_x0_local) <= 6:
            drag_vsplit = True
            return
        if event == cv2.EVENT_MOUSEMOVE and drag_vsplit:
            # Clamp stream area width
            v_split_x = max(200, min(int(x), cw - 320))
            return
        if event == cv2.EVENT_LBUTTONUP and drag_vsplit:
            drag_vsplit = False
            return

        # Horizontal split bars inside right panel
        hs1_y = ui_lines.get("hs1_y", 0)
        hs2_y = ui_lines.get("hs2_y", 0)
        sec_top = ui_lines.get("sec_top", 0)
        sec_bottom = ui_lines.get("sec_bottom", ch - 100)
        if event == cv2.EVENT_LBUTTONDOWN and in_panel:
            if abs(y - hs1_y) <= 6:
                drag_hsplit = 1
                return
            if abs(y - hs2_y) <= 6:
                drag_hsplit = 2
                return
        if event == cv2.EVENT_MOUSEMOVE and drag_hsplit is not None:
            total_h = max(1, sec_bottom - sec_top)
            ratio = (y - sec_top) / total_h
            ratio = max(0.05, min(0.95, ratio))
            if drag_hsplit == 1:
                # keep order: hsplit1 < hsplit2 - min_gap
                min_gap = 0.08
                hsplit1_ratio = min(ratio, hsplit2_ratio - min_gap)
            else:
                min_gap = 0.08
                hsplit2_ratio = max(ratio, hsplit1_ratio + min_gap)
            return
        if event == cv2.EVENT_LBUTTONUP and drag_hsplit is not None:
            drag_hsplit = None
            return

        # Column splitter drag inside lower area when side_by_side
        if side_by_side and in_panel:
            # Use stored lines
            hs1_y = ui_lines.get("hs1_y", 0)
            sec_top = ui_lines.get("sec_top", 0)
            sec_bottom = ui_lines.get("sec_bottom", ch - 100)
            lower_top = hs1_y + 12
            lower_bot = sec_bottom - 8
            # Current split X in canvas coords
            split_x = panel_x0_local + 12 + int(col_split_ratio * max(10, panel_w - 24))
            if event == cv2.EVENT_LBUTTONDOWN and lower_top <= y <= lower_bot and abs(x - split_x) <= 6:
                drag_colsplit = True
                return
            if event == cv2.EVENT_MOUSEMOVE and drag_colsplit:
                # Update ratio within bounds
                denom = max(10, panel_w - 24)
                col_split_ratio = max(0.1, min(0.9, (x - (panel_x0_local + 12)) / denom))
                return
            if event == cv2.EVENT_LBUTTONUP and drag_colsplit:
                drag_colsplit = False
                return

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
            # Template grid clicks (left=select current; right=toggle multi-select)
            for idx, (bx, by, bw, bh) in enumerate(tpl_tile_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx < len(tpl_list):
                        if event == cv2.EVENT_RBUTTONDOWN:
                            p = tpl_list[idx]
                            if p in selected_tpls:
                                selected_tpls.remove(p)
                            else:
                                selected_tpls.add(p)
                        else:
                            load_template_at(idx)
                    return
            # Script control buttons
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_scripts):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Run
                        if script_list:
                            run_script_by_index(max(0, script_index))
                    elif idx == 1:  # Stop
                        stop_script()
                    elif idx == 2:  # Reload
                        refresh_scripts()
                    return
            # Script list clicks
            for idx, (bx, by, bw, bh) in enumerate(script_item_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx < len(script_list):
                        script_index = idx
                    return

            # Sequence buttons row 1
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_seq1):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Add Find+Click (current tpl)
                        if tpl_path:
                            seq_steps.append({"type": "FIND_CLICK_ONE", "tpl": tpl_path, "threshold": args.threshold})
                            seq_selected = len(seq_steps) - 1
                            seq_status = f"Added Find+Click {os.path.basename(tpl_path)}"
                    elif idx == 1:  # Add FindAny+Click (selected tpls)
                        tpls = [p for p in tpl_list if p in selected_tpls]
                        if not tpls and tpl_path:
                            tpls = [tpl_path]
                        if tpls:
                            seq_steps.append({"type": "FIND_CLICK_ANY", "tpls": tpls, "threshold": args.threshold})
                            seq_selected = len(seq_steps) - 1
                            seq_status = f"Added FindAny+Click x{len(tpls)}"
                    elif idx == 2:  # Add Wait
                        seq_steps.append({"type": "WAIT", "ms": 500})
                        seq_selected = len(seq_steps) - 1
                        seq_status = "Added Wait 500ms"
                    elif idx == 3:  # Loop->0
                        seq_steps.append({"type": "LOOP", "to": 0})
                        seq_selected = len(seq_steps) - 1
                        seq_status = "Added Loop->0"
                    return
            # Sequence buttons row 2
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_seq2):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx == 0:  # Run
                        start_sequence()
                    elif idx == 1:  # Stop
                        stop_sequence()
                    elif idx == 2:  # Clear
                        seq_steps.clear(); seq_selected = None
                    elif idx == 3:  # Up
                        if seq_selected is not None and seq_selected > 0:
                            i = seq_selected
                            seq_steps[i-1], seq_steps[i] = seq_steps[i], seq_steps[i-1]
                            seq_selected -= 1
                    elif idx == 4:  # Down
                        if seq_selected is not None and seq_selected < len(seq_steps)-1:
                            i = seq_selected
                            seq_steps[i+1], seq_steps[i] = seq_steps[i], seq_steps[i+1]
                            seq_selected += 1
                    elif idx == 5:  # Del
                        if seq_selected is not None and 0 <= seq_selected < len(seq_steps):
                            del seq_steps[seq_selected]
                            if not seq_steps:
                                seq_selected = None
                            else:
                                seq_selected = min(seq_selected, len(seq_steps)-1)
                    return
            # REC toggle
            for idx, (bx, by, bw, bh) in enumerate(btn_rects_seq_rec):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    rec_mode = not rec_mode
                    return
            # Sequence list clicks
            for idx, (bx, by, bw, bh) in enumerate(seq_item_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if idx < len(seq_steps):
                        seq_selected = idx
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

        # Handle right-click in panel for template grid multi-select toggle
        if event == cv2.EVENT_RBUTTONDOWN and in_panel:
            for idx, (bx, by, bw, bh) in enumerate(tpl_tile_rects):
                if bx <= x <= bx + bw and by <= y <= by + bh and idx < len(tpl_list):
                    p = tpl_list[idx]
                    if p in selected_tpls:
                        selected_tpls.remove(p)
                    else:
                        selected_tpls.add(p)
                    return

        # Default: left-click taps current match center
        if event == cv2.EVENT_LBUTTONDOWN and not in_panel:
            if latest_center is not None:
                cx, cy = latest_center
                bot.click(int(cx), int(cy))
                print(f"tap: {cx} {cy}")
            # Recording: add a step using current template
            if rec_mode and tpl_path:
                seq_steps.append({"type": "FIND_CLICK_ONE", "tpl": tpl_path, "threshold": args.threshold})
                seq_selected = len(seq_steps) - 1

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
            # Use dynamic vertical splitter
            stream_area_w = max(200, min(v_split_x, cw - 320))
            panel_x0 = stream_area_w
            panel_w = cw - stream_area_w
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
                    f"Keys: c=auto  r=roi  g=gray  +/-=thr  s=snap  t=new_tpl  m=save_match_tpl  esc=cancel_draw  q=quit",
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

            # Template grid with uniform tiles
            tpl_tile_rects = []
            grid_x = panel_origin_x
            # Controls area height (title+keymap+rows of buttons)
            controls_h = 270
            sec_top = panel_origin_y + controls_h
            sec_bottom = ch - 100  # leave space for status lines
            # Compute split positions
            hs1_y = int(sec_top + hsplit1_ratio * (sec_bottom - sec_top))
            hs2_y = int(sec_top + hsplit2_ratio * (sec_bottom - sec_top))
            # Update UI lines for event handling
            ui_lines.update({"hs1_y": hs1_y, "hs2_y": hs2_y, "panel_x0": panel_x0, "sec_top": sec_top, "sec_bottom": sec_bottom})
            # Draw split bars
            cv2.line(canvas, (panel_x0 + 6, hs1_y), (panel_x0 + panel_w - 16, hs1_y), (90, 90, 90), 2)
            cv2.line(canvas, (panel_x0 + 6, hs2_y), (panel_x0 + panel_w - 16, hs2_y), (90, 90, 90), 2)

            # Section rectangles
            sec1_top, sec1_bot = sec_top + 8, hs1_y - 8
            sec2_top, sec2_bot = hs1_y + 12, hs2_y - 8
            sec3_top, sec3_bot = hs2_y + 12, sec_bottom - 8

            grid_y = sec1_top
            grid_w = panel_x0 + panel_w - 16 - grid_x
            # Tile size and padding
            tile = 96
            pad = 8
            cols = max(1, grid_w // (tile + pad))
            # rows limited by section 1 height
            rows = max(1, max(1, (sec1_bot - grid_y) // (tile + pad)))
            max_tiles = cols * rows
            shown = min(max_tiles, len(tpl_list))
            # Build thumbnail cache
            if not hasattr(main, "_thumb_cache"):
                main._thumb_cache = {}
            cache = main._thumb_cache
            for i in range(shown):
                r = i // cols
                c = i % cols
                x1 = grid_x + c * (tile + pad)
                y1 = grid_y + r * (tile + pad)
                x2 = x1 + tile
                y2 = y1 + tile
                path = tpl_list[i]
                # highlight border if selected / current index
                bg = (60, 60, 60) if i != tpl_index else (80, 80, 110)
                cv2.rectangle(canvas, (x1 - 2, y1 - 2), (x2 + 2, y2 + 22), bg, -1)
                # load/resize thumbnail
                thumb = cache.get(path)
                if thumb is None:
                    img0 = cv2.imread(path, cv2.IMREAD_COLOR)
                    if img0 is None:
                        img0 = np.zeros((tile, tile, 3), dtype=np.uint8)
                    th, tw = img0.shape[:2]
                    s2 = min(tile / max(1, tw), tile / max(1, th))
                    rw2, rh2 = max(1, int(tw * s2)), max(1, int(th * s2))
                    thumb = np.zeros((tile, tile, 3), dtype=np.uint8)
                    rs = cv2.resize(img0, (rw2, rh2), interpolation=cv2.INTER_AREA)
                    xo = (tile - rw2) // 2
                    yo = (tile - rh2) // 2
                    thumb[yo:yo+rh2, xo:xo+rw2] = rs
                    cache[path] = thumb
                canvas[y1:y2, x1:x2] = thumb
                # multi-select visual
                path_sel = tpl_list[i] in selected_tpls
                if path_sel:
                    cv2.rectangle(canvas, (x1 - 2, y1 - 2), (x2 + 2, y2 + 2), (0, 215, 255), 2)
                # filename
                name = os.path.basename(path)
                cv2.rectangle(canvas, (x1, y2), (x2, y2 + 18), (30, 30, 30), -1)
                cv2.putText(canvas, name[:12], (x1 + 4, y2 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
                tpl_tile_rects.append((x1 - 2, y1 - 2, (x2 + 2) - (x1 - 2), (y2 + 22) - (y1 - 2)))

            # Lower area: Scripts and Sequence side-by-side
            lower_top = hs1_y + 12
            lower_bot = sec_bottom - 8
            left_x = panel_x0 + 12
            left_w = int(col_split_ratio * max(10, panel_w - 24))
            right_x = left_x + left_w + 8
            right_w = max(0, (panel_w - 24) - left_w)
            # Draw column splitter
            split_x = left_x + left_w + 4
            cv2.line(canvas, (split_x, lower_top), (split_x, lower_bot), (90, 90, 90), 2)

            # Scripts in left column
            sc_y = lower_top
            panel_origin_x_left = left_x
            cv2.putText(canvas, "Scripts", (panel_origin_x_left, sc_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200,200,200), 2, cv2.LINE_AA)
            btn_rects_scripts = _draw_buttons(canvas, ["Run", "Stop", "Reload"], origin=(panel_origin_x_left, sc_y + 10))
            script_item_rects = []
            sl_y = sc_y + 48
            item_h = 22
            max_items = max(2, max(0, (lower_bot - sl_y - 10)) // item_h)
            right_limit_left = left_x + max(0, left_w - 6)
            for i in range(min(max_items, len(script_list))):
                name = os.path.basename(script_list[i])
                y1 = sl_y + i * item_h
                y2 = y1 + item_h - 4
                x1 = panel_origin_x_left
                x2 = right_limit_left
                bg = (40, 40, 40) if i != script_index else (90, 70, 70)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), bg, -1)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (90, 90, 90), 1)
                cv2.putText(canvas, name[:48], (x1 + 8, y1 + item_h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
                script_item_rects.append((x1, y1, x2 - x1, y2 - y1))

            # Sequence in right column
            seq_y = lower_top
            panel_origin_x_right = right_x
            cv2.putText(canvas, "Sequence", (panel_origin_x_right, seq_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200,200,200), 2, cv2.LINE_AA)
            btn_rects_seq1 = _draw_buttons(canvas, ["Add One", "Add Any", "Add Wait", "Loop->0"], origin=(panel_origin_x_right, seq_y + 10))
            btn_rects_seq2 = _draw_buttons(canvas, ["Run Seq", "Stop Seq", "Clear", "Up", "Down", "Del"], origin=(panel_origin_x_right, seq_y + 50))
            btn_rects_seq_rec = _draw_buttons(canvas, [f"REC:{'ON' if rec_mode else 'OFF'}"], origin=(panel_origin_x_right, seq_y + 90))
            seq_item_rects = []
            qy = seq_y + 130
            item_h2 = 22
            max_items2 = max(1, max(0, (lower_bot - qy - 10)) // item_h2)
            right_limit_right = panel_x0 + panel_w - 16
            for i in range(min(max_items2, len(seq_steps))):
                step = seq_steps[i]
                y1 = qy + i * item_h2
                y2 = y1 + item_h2 - 4
                x1 = panel_origin_x_right
                x2 = right_limit_right
                bg = (42, 42, 42) if i != (seq_selected or -1) else (90, 90, 70)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), bg, -1)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (90, 90, 90), 1)
                label = render_step_label(step)
                cv2.putText(canvas, label[:60], (x1 + 6, y1 + item_h2 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230,230,230), 1, cv2.LINE_AA)
                seq_item_rects.append((x1, y1, x2 - x1, y2 - y1))

            # Status lines
            y_status = ch - 50
            if script_running or script_status:
                cv2.putText(canvas, script_status, (panel_origin_x, y_status), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180,180,140), 2, cv2.LINE_AA)
                y_status -= 20
            if seq_running or seq_status:
                cv2.putText(canvas, seq_status, (panel_origin_x, y_status), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180,200,180), 2, cv2.LINE_AA)

            # FPS/status on bottom of panel
            status_text = status + f" | {fps_smooth:.1f} FPS"
            cv2.putText(canvas, status_text, (panel_origin_x, ch - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180,180,180), 2, cv2.LINE_AA)

            # Draw vertical splitter handle
            cv2.line(canvas, (panel_x0, 0), (panel_x0, ch), (80, 80, 80), 2)

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
            elif key == ord('t'):
                # Toggle new template draw mode
                if draw_mode == 'tpl':
                    draw_mode = None
                    dragging = False
                    drag_start_frame = None
                    drag_end_frame = None
                    print("New template draw: canceled")
                else:
                    draw_mode = 'tpl'
                    dragging = False
                    drag_start_frame = None
                    drag_end_frame = None
                    print("New template draw: click-drag on stream to save")
            elif key == 27:  # ESC
                if draw_mode is not None:
                    draw_mode = None
                    dragging = False
                    drag_start_frame = None
                    drag_end_frame = None
                    print("Draw mode canceled")
            elif key == ord('m'):
                # Save current match rect as a new template
                if latest_rect is not None and last_frame is not None:
                    x1, y1, x2, y2 = map(int, latest_rect)
                    x1 = max(0, min(x1, last_frame.shape[1]-1))
                    x2 = max(0, min(x2, last_frame.shape[1]))
                    y1 = max(0, min(y1, last_frame.shape[0]-1))
                    y2 = max(0, min(y2, last_frame.shape[0]))
                    if x2 > x1 and y2 > y1:
                        crop = last_frame[y1:y2, x1:x2].copy()
                        os.makedirs('img', exist_ok=True)
                        ts = time.strftime('%Y%m%d_%H%M%S')
                        out = os.path.join('img', f'tpl_{x2-x1}x{y2-y1}_{ts}.png')
                        cv2.imwrite(out, crop)
                        print(f"Saved new template from match: {out}")
                        refresh_templates()
                        if out in tpl_list:
                            load_template_at(tpl_list.index(out))
                        else:
                            tpl_list.insert(0, out)
                            load_template_at(0)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyWindow(win)
        bot.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
