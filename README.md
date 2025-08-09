# ADBImgDetection

Detect images from an Android device via ADB and perform actions like click and swipe.

## Quick start

Requirements:
- Python 3.10+
- ADB server running and phone connected (USB or TCP)
- Packages: pure-python-adb, opencv-python, numpy

Install deps (example):

```bash
pip install pure-python-adb opencv-python numpy
```

Run the CLI:

```bash
python main.py --help
```

Examples:

```bash
# Tap at coords
python main.py click 500 800

# Swipe from (x1,y1) to (x2,y2) in 300ms
python main.py swipe 200 1200 900 1200 300

# Find an image and click the first match
python main.py find market.png --threshold 0.6 --click

# Wait for an image to appear and tap it when found
python main.py wait moneyshop.png --threshold 0.55 --timeout 20 --click

# Interactively capture a new template into img/ (no preview by default)
python main.py capture my_button.png

# Run a Python automation flow that uses Bot()
python main.py runpy examples/my_flow.py -- --any --args --for --your --script

# Inspect device coordinates interactively (q=quit, r=refresh, s=save)
python main.py coords --scale 0.6
```

## Easier way to create templates (no manual crop/rename)

Use the interactive capture command. It takes a device screenshot and opens a resizable window to select a rectangle (ROI). It then saves the crop under `img/` automatically.

```bash
python main.py capture market.png
```

Tips:
- The window supports drag-select. Press Enter/Space to confirm.
- Add `--preview` to briefly show the saved crop.
- Use `--overwrite` to replace an existing file; otherwise a numeric suffix is added.

## Programmatic API

```python
from bot import Bot

b = Bot()
b.tap_image("market.png", threshold=0.55)
b.wait_for_image("moneyshop.png", timeout=20, click_on_appear=True)
b.click(540, 1750)
b.swipe(540, 1600, 540, 800, 500)
```

See `examples/my_flow.py` for a full flow.

## Scripting guide: write flexible automation flows

This section shows how to script the bot with Python for robust, verifiable flows (wait for UI, act, and confirm outcomes). Use `python main.py runpy your_script.py` to run.

### API overview (Bot)
- click(x, y): tap absolute screen coordinates.
- swipe(x1, y1, x2, y2, duration_ms): swipe/drag.
- screenshot() -> np.ndarray: take a device screenshot (BGR image).
- match_template(template_path, threshold=0.45, return_image=True) -> (img, rects): find matches of `img/<template>`; `rects` is Nx4 [x1,y1,x2,y2].
- tap_image(template_path, threshold=0.45, clicks=1) -> bool: tap center of first match.
- wait_for_image(template_path, threshold=0.45, timeout=30, poll=0.5, click_on_appear=False) -> bool: wait until visible; optional auto-tap.
- capture_template(out_name, rect=None, show_preview=False, overwrite=False) -> str: interactively create a template under `img/`.

Templates live in `img/`. You can pass bare names like `mainmenumyfarm.png`; the bot auto-prefixes `img/`.

### First script: wait, tap, verify
Create a script (e.g. `examples/advanced_flow.py`) like this:

```python
import time
from bot import Bot


def exists(b: Bot, template: str, threshold: float = 0.7) -> bool:
	_, rects = b.match_template(template, threshold=threshold, return_image=False)
	return len(rects) > 0


def wait_until_gone(b: Bot, template: str, threshold: float = 0.7, timeout: float = 20.0, poll: float = 0.5) -> bool:
	end = time.time() + timeout
	while time.time() < end:
		if not exists(b, template, threshold):
			return True
		time.sleep(poll)
	return False


def main():
	b = Bot()

	# 1) Wait for a known screen and click on appear
	b.wait_for_image("mainmenumyfarm.png", threshold=0.8, timeout=20, click_on_appear=True)
	time.sleep(1.0)

	# 2) Tap a button by template
	if not b.tap_image("harvestallcrops.png", threshold=0.8):
		print("harvest button not found; aborting")
		return

	# 3) Verify the button disappears (e.g., action consumed)
	gone = wait_until_gone(b, "harvestallcrops.png", threshold=0.75, timeout=10)
	print(f"harvest button gone: {gone}")

	# 4) Optional swipe
	b.swipe(200, 1200, 900, 1200, 300)

	# 5) Sanity check
	still_ok = exists(b, "mainmenumyfarm.png", threshold=0.7)
	print(f"back at main menu: {still_ok}")


if __name__ == "__main__":
	main()
```

Run it:

```bash
python main.py runpy examples/advanced_flow.py
```

### Patterns for robust flows
- Wait-then-act: Prefer `wait_for_image(..., click_on_appear=True)` before tapping.
- Verify outcomes:
  - Appear: `wait_for_image(success.png, timeout=10)`.
  - Disappear: poll with `match_template` until no rects (see `wait_until_gone` helper above).
- Conditional branches: use `match_template` to decide next step.
- Small delays: add short `time.sleep(0.2–0.5s)` after taps so the UI updates before verifying.

### Choosing a good threshold
- Start around 0.6–0.8 for clean UI elements.
- If you get false positives, increase the threshold or crop a tighter, more unique area.
- If you get misses, slightly decrease threshold or recapture the template with sharper edges/high contrast.

### Create and manage templates
Use the built-in capture tool to avoid manual cropping:

```bash
python main.py capture my_button.png         # saves to img/my_button.png
python main.py capture my_button.png --preview
```

Tips:
- Capture the smallest unique region (icon + a bit of padding), not the whole screen.
- Avoid dynamic text/timers in the crop.
- You can overwrite or keep multiple variants; name them clearly (e.g., `buy_btn_day.png`, `buy_btn_night.png`).

### Debug matches visually
From the CLI, you can preview where matches occur:

```bash
python main.py find harvestallcrops.png --threshold 0.8 --show
```

This draws rectangles over the screenshot in a temporary window.

### Inspect coordinates easily
Use the interactive viewer that shows device coordinates at the mouse cursor:

```bash
python main.py coords
```

Keys:
- q / ESC: quit
- r: refresh screenshot
- s: save current screenshot to img/coords_YYYYmmdd_HHMMSS.png
- Left click: prints the exact device coordinates to the console

### Keep your workflow in Markdown (docs and run commands)
While flows run as Python, documenting them in Markdown keeps them organized. Example `examples/workflow.md`:

```md
# Harvest workflow

- [ ] Wait for main menu and click it on appear
- [ ] Tap harvest-all and confirm it disappears
- [ ] Swipe bottom nav
- [ ] Verify we are back at main menu

Run:

```bash
python main.py runpy examples/advanced_flow.py
```
```

You can keep multiple sections (morning/evening routines), paste CLI probes (find/show), and link to your scripts.

