"""
Core ADB image-detection bot utilities.

Provides:
- Bot: connect to device, click, swipe, screenshot
- Template matching: match_template, tap_image, wait_for_image
- Template capture: capture_template (interactive ROI) to simplify creating images
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional

import cv2  # type: ignore
import numpy as np  # type: ignore
import re

try:
    from ppadb.client import Client as AdbClient  # type: ignore
except Exception:  # pragma: no cover - optional at dev time
    AdbClient = None  # type: ignore


IMG_DIR = "img"


def ensure_img_dir() -> None:
    if not os.path.isdir(IMG_DIR):
        os.makedirs(IMG_DIR, exist_ok=True)


def _prefix_img_path(path: str) -> str:
    # Allow passing bare names like "market.png" and auto-prefix with img/
    if not path.lower().startswith(IMG_DIR + os.sep):
        return os.path.join(IMG_DIR, path)
    return path


def rect_center(rect: List[int]) -> Tuple[int, int]:
    # rect = [x1, y1, x2, y2]
    return int((rect[0] + rect[2]) / 2), int((rect[1] + rect[3]) / 2)


def draw_rectangles(img: np.ndarray, rects: np.ndarray, color=(0, 255, 255), thickness=2) -> np.ndarray:
    out = img.copy()
    for (x1, y1, x2, y2) in rects:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness)
    return out


def _require_tesseract():
    try:
        import pytesseract  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "pytesseract and the Tesseract OCR engine are required.\n"
            "Install: pip install pytesseract\n"
            "And ensure the 'tesseract' binary is installed and on PATH (e.g., apt install tesseract-ocr)."
        ) from e
    return pytesseract


@dataclass
class Bot:
    host: str = "127.0.0.1"
    port: int = 5037
    max_results: int = 42
    device: Optional[object] = None
    # Stores the most recent match rectangle as (x1, y1, x2, y2) or None if no match yet
    last_rect: Optional[Tuple[int, int, int, int]] = None

    def __post_init__(self):
        if self.device is None:
            self.device = self._connect_device()

    def _connect_device(self):
        if AdbClient is None:
            raise RuntimeError("pure-python-adb (ppadb) is not installed. Install with: pip install pure-python-adb")
        client = AdbClient(host=self.host, port=self.port)
        devices = client.devices()
        if not devices:
            raise RuntimeError("No ADB device connected. Start adb server and connect a device (adb devices).")
        return devices[0]

    # Low-level input
    def click(self, x: int, y: int) -> None:
        self.device.shell(f"input tap {x} {y}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    # Screenshot
    def screenshot(self) -> np.ndarray:
        """Return a BGR image as numpy array."""
        raw = self.device.screencap()
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Failed to decode screenshot")
        return img  # BGR

    # Template matching
    def match_template(
        self,
        template_path: str,
        threshold: float = 0.45,
        return_image: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        template_path = _prefix_img_path(template_path)
        ensure_img_dir()
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise RuntimeError(f"Failed to load template: {template_path}")

        screenshot = self.screenshot()
        if template.ndim != 3 or screenshot.ndim != 3 or template.shape[2] != screenshot.shape[2]:
            raise ValueError("Template and screenshot must have same number of color channels")

        res = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        locs = list(zip(*loc[::-1]))

        if not locs:
            # No matches – clear last_rect and return
            self.last_rect = None
            return (screenshot if return_image else np.empty((0,)), np.empty((0, 4), dtype=np.int32))

        rects: List[List[int]] = []
        th, tw = template.shape[:2]
        for (x, y) in locs:
            rects.append([int(x), int(y), int(x + tw), int(y + th)])

        # Trick: duplicate rects to allow groupRectangles to return singles when groupThreshold>0
        rects = rects + rects
        grouped, _weights = cv2.groupRectangles(rects, groupThreshold=1, eps=0.01)
        if grouped is None or len(grouped) == 0:
            grouped = np.array(rects[: self.max_results], dtype=np.int32)
        if len(grouped) > self.max_results:
            grouped = grouped[: self.max_results]

        # Save the best/first grouped rect as the last match
        if len(grouped) > 0:
            x1, y1, x2, y2 = map(int, grouped[0].tolist())
            self.last_rect = (x1, y1, x2, y2)
        else:
            self.last_rect = None

        if return_image:
            vis = draw_rectangles(screenshot, grouped)
            return vis, grouped
        else:
            return screenshot, grouped

    def click_last_match(self, clicks: int = 1) -> bool:
        """Click the center of the most recent matched rectangle.

        Returns True on click, False if there is no stored match.
        """
        if not self.last_rect:
            print("No last match to click")
            return False
        x1, y1, x2, y2 = map(int, self.last_rect)
        cx, cy = rect_center([x1, y1, x2, y2])
        for _ in range(max(1, clicks)):
            self.click(cx, cy)
            time.sleep(0.1)
        print(f"Tapped last match at ({cx},{cy})")
        return True

    def tap_image(self, template_path: str, threshold: float = 0.45, clicks: int = 1) -> bool:
        img, rects = self.match_template(template_path, threshold=threshold, return_image=False)
        if len(rects) == 0:
            print(f"No match: {template_path}")
            return False
        cx, cy = rect_center(rects[0].tolist())
        for _ in range(max(1, clicks)):
            self.click(cx, cy)
            time.sleep(0.1)
        print(f"Tapped {template_path} at ({cx},{cy})")
        return True

    def wait_for_image(
        self,
        template_path: str,
        threshold: float = 0.45,
        timeout: float = 30.0,
        poll: float = 0.5,
        click_on_appear: bool = False,
    ) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            _, rects = self.match_template(template_path, threshold=threshold, return_image=False)
            if len(rects) > 0:
                cx, cy = rect_center(rects[0].tolist())
                print(f"Found {template_path} at ({cx},{cy})")
                if click_on_appear:
                    self.click(cx, cy)
                return True
            time.sleep(poll)
        print(f"Timeout waiting for {template_path}")
        return False

    # Interactive capture to simplify creating templates
    def capture_template(
        self,
        out_name: str,
        rect: Optional[Tuple[int, int, int, int]] = None,  # x, y, w, h
        show_preview: bool = False,
        overwrite: bool = False,
    ) -> str:
        """
        Takes a screenshot, lets you select an ROI (or use provided rect), and saves to img/out_name.
        Returns the saved file path.
        """
        ensure_img_dir()
        out_path = _prefix_img_path(out_name)
        if os.path.exists(out_path) and not overwrite:
            # auto-unique
            base, ext = os.path.splitext(out_path)
            i = 1
            while os.path.exists(f"{base}_{i}{ext}"):
                i += 1
            out_path = f"{base}_{i}{ext}"

        shot = self.screenshot()
        roi = rect
        if roi is None:
            # Use OpenCV GUI to select
            from_center = False
            show_crosshair = True
            disp = shot.copy()
            cv2.namedWindow("Select ROI", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Select ROI", 800, 450)
            r = cv2.selectROI("Select ROI", disp, showCrosshair=show_crosshair, fromCenter=from_center)
            cv2.destroyWindow("Select ROI")
            x, y, w, h = map(int, r)
        else:
            x, y, w, h = map(int, roi)
        if w <= 0 or h <= 0:
            raise ValueError("ROI has zero width/height")
        crop = shot[y : y + h, x : x + w]
        if crop.size == 0:
            raise RuntimeError("Invalid ROI crop")
        cv2.imwrite(out_path, crop)
        if show_preview:
            preview = crop.copy()
            cv2.namedWindow("Saved Template", cv2.WINDOW_NORMAL)
            cv2.imshow("Saved Template", preview)
            cv2.waitKey(500)
            cv2.destroyWindow("Saved Template")
        print(f"Saved template: {out_path} ({w}x{h})")
        return out_path

    # --- OCR utilities ---
    def _prep_roi_for_ocr(self, roi_img: np.ndarray, invert: bool = False) -> np.ndarray:
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        # Slight blur to reduce noise
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        # Adaptive threshold can be more robust; fall back to Otsu if needed
        try:
            th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 31, 9)
        except Exception:
            _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if invert:
            th = cv2.bitwise_not(th)
        return th

    def read_text_in_roi(
        self,
        roi: Tuple[int, int, int, int],  # x, y, w, h
        psm: int = 7,
        whitelist: Optional[str] = None,
        invert: bool = False,
    ) -> str:
        """
        OCR any text within the given ROI. Returns the raw text (stripped).
        Requires: pytesseract + Tesseract-OCR installed.
        """
        x, y, w, h = map(int, roi)
        if w <= 0 or h <= 0:
            raise ValueError("ROI has zero width/height")
        img = self.screenshot()
        crop = img[y : y + h, x : x + w]
        if crop.size == 0:
            raise RuntimeError("Invalid ROI crop for OCR")
        proc = self._prep_roi_for_ocr(crop, invert=invert)
        pytesseract = _require_tesseract()
        cfg = f"--psm {int(psm)} --oem 3"
        if whitelist:
            cfg += f" -c tessedit_char_whitelist={whitelist}"
        txt = pytesseract.image_to_string(proc, config=cfg)
        return (txt or "").strip()

    def read_number_in_roi(
        self,
        roi: Tuple[int, int, int, int],  # x, y, w, h
        number_type: str = "int",  # 'int' or 'float'
        psm: int = 7,
        invert: bool = False,
    ) -> Optional[float]:
        """
        OCR digits in ROI and parse a number. Returns float or None if not found.
        number_type='int' will coerce to int (as float return type), 'float' keeps decimals.
        """
        wl = "0123456789." if number_type == "float" else "0123456789"
        text = self.read_text_in_roi(roi, psm=psm, whitelist=wl, invert=invert)
        # Extract first number from text
        m = re.search(r"\d+[\.,]?\d*", text.replace(",", "."))
        if not m:
            return None
        try:
            val = float(m.group(0))
        except Exception:
            return None
        if number_type == "int":
            return float(int(round(val)))
        return val

    def read_number_near_template(
        self,
        template_path: str,
        offset: Tuple[int, int, int, int],  # dx, dy, w, h relative to match top-left
        threshold: float = 0.45,
        number_type: str = "int",
        psm: int = 7,
        invert: bool = False,
    ) -> Optional[float]:
        """
        Find template, then OCR a number in a ROI defined relative to the template's top-left.
        offset=(dx,dy,w,h) where dx,dy are from the match's x1,y1.
        """
        _, rects = self.match_template(template_path, threshold=threshold, return_image=False)
        if len(rects) == 0:
            return None
        x1, y1, x2, y2 = map(int, rects[0].tolist())
        dx, dy, w, h = map(int, offset)
        roi = (x1 + dx, y1 + dy, w, h)
        return self.read_number_in_roi(roi, number_type=number_type, psm=psm, invert=invert)
