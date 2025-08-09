# Python API Reference

Module: [bot.py](../bot.py)
Class: [`bot.Bot`](../bot.py)

Construction
- Bot(host: str = "127.0.0.1", port: int = 5037, max_results: int = 42, device: Optional[object] = None)
  - Connects to the first available ADB device in `__post_init__`.
  - Raises:
    - RuntimeError if pure-python-adb is missing or no ADB device is connected.

Low-level input
- [`bot.Bot.click`](../bot.py)
  - Signature: click(x: int, y: int) -> None
  - Sends a tap at absolute device coordinates.

- [`bot.Bot.swipe`](../bot.py)
  - Signature: swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None
  - Swipes from (x1,y1) to (x2,y2) over duration_ms milliseconds.

Screenshots
- [`bot.Bot.screenshot`](../bot.py)
  - Signature: screenshot() -> numpy.ndarray
  - Returns a BGR image (OpenCV convention) of the device screen.
  - Raises: RuntimeError if screenshot cannot be decoded.

Template matching
- [`bot.Bot.match_template`](../bot.py)
  - Signature: match_template(template_path: str, threshold: float = 0.45, return_image: bool = True) -> tuple[numpy.ndarray, numpy.ndarray]
  - Behavior:
    - Auto-prefixes template with img/ if not already.
    - Returns (image, rects) where rects is an Nx4 array of [x1, y1, x2, y2] in device coordinates.
    - image is:
      - Annotated screenshot with rectangles if return_image=True.
      - Raw screenshot if return_image=False (or empty array when no matches).
  - Raises: FileNotFoundError (missing template), ValueError (channel mismatch).

- [`bot.Bot.tap_image`](../bot.py)
  - Signature: tap_image(template_path: str, threshold: float = 0.45, clicks: int = 1) -> bool
  - Taps the center of the first match `clicks` times.
  - Returns: True if tapped, False if no match ≥ threshold.

- [`bot.Bot.wait_for_image`](../bot.py)
  - Signature: wait_for_image(template_path: str, threshold: float = 0.45, timeout: float = 30.0, poll: float = 0.5, click_on_appear: bool = False) -> bool
  - Polls until a match is found or timeout.
  - If click_on_appear=True, automatically clicks the first match.
  - Returns: True if found, False on timeout.

Template capture
- [`bot.Bot.capture_template`](../bot.py)
  - Signature: capture_template(out_name: str, rect: Optional[tuple[int, int, int, int]] = None, show_preview: bool = False, overwrite: bool = False) -> str
  - Captures a screenshot and lets you select an ROI (or uses rect) to save under img/out_name.
  - Returns: Saved file path (may auto-append _N to avoid overwrite).
  - Raises: ValueError (invalid ROI), RuntimeError (invalid crop).

OCR utilities
- [`bot.Bot.read_text_in_roi`](../bot.py)
  - Signature: read_text_in_roi(roi: tuple[int, int, int, int], psm: int = 7, whitelist: Optional[str] = None, invert: bool = False) -> str
  - OCRs text within the ROI. Requires pytesseract and system tesseract.
  - Returns: stripped string (can be empty).
  - Raises: RuntimeError if Tesseract not installed or ROI invalid.

- [`bot.Bot.read_number_in_roi`](../bot.py)
  - Signature: read_number_in_roi(roi: tuple[int, int, int, int], number_type: str = "int", psm: int = 7, invert: bool = False) -> Optional[float]
  - Parses first number from OCR text. number_type="int" rounds/coerces to int (as float); "float" keeps decimals.
  - Returns: float value or None if no number found.

- [`bot.Bot.read_number_near_template`](../bot.py)
  - Signature: read_number_near_template(template_path: str, offset: tuple[int, int, int, int], threshold: float = 0.45, number_type: str = "int", psm: int = 7, invert: bool = False) -> Optional[float]
  - Finds template, derives ROI from its top-left by offset=(dx,dy,w,h), then OCRs a number.
  - Returns: float or None if template/number not found.

Helpers (module-level)
- [`bot.ensure_img_dir`](../bot.py): ensure img/ exists.
- [`bot.draw_rectangles`](../bot.py): annotate an image with rectangles.
- [`bot.rect_center`](../bot.py): compute center of [x1,y1,x2,y2].

Notes
- Thresholds: start at 0.6–0.8 for crisp UI icons; lower if necessary.
- Coordinates: all rects are device pixel coordinates.