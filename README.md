# Mobile Bot Base (streaming)

Image-based automation for Android. Now with live streaming capture.

What changed
- You can keep using the same Bot API (match_template, tap_image, wait_for_image), but source frames from a continuous stream for lower latency.
- Use `StreamBot` as a drop-in replacement: it overrides screenshot() to return the latest stream frame.

## Quick start

Requirements:
- Python 3.10+
- Android platform tools (adb) and a connected device (`adb devices`)
- Python packages: pure-python-adb, opencv-python, numpy
- For streaming via adb/scrcpy: `pip install av`
- Optional OCR: pytesseract + system tesseract-ocr

Install deps (example):

```bash
pip install pure-python-adb opencv-python numpy av
# OCR (optional)
pip install pytesseract
```

Run a stream-based example:

```bash
python main.py runpy examples/my_flow.py
```

The example uses:

```python
from stream_bot import StreamBot as Bot
b = Bot(source="adb", size="1280x720", bit_rate="8000000")
b.wait_for_image("mainmenumyfarm.png", threshold=0.8, timeout=20, click_on_appear=True)
```

CLI still works for quick probes and utilities:

```bash
python main.py --help
```

- capture: interactively save a new template into img/
- find/wait: single-shot screenshot based
- coords: inspect coordinates over a screenshot

## Templates

Keep your template PNGs under `img/` (we preserved your images).
Use `python main.py capture name.png` to create new ones quickly.

## Streaming lab tool

See `stream_tests/` for a standalone streaming matcher and tips.
It helps evaluate latency and thresholds live.


