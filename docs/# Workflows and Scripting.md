# Workflows and Scripting Patterns

Write flows in Python using [`bot.Bot`](../bot.py) and run via CLI’s runpy.

Minimal example
```python
from bot import Bot
b = Bot()
b.wait_for_image("mainmenumyfarm.png", threshold=0.8, timeout=20, click_on_appear=True)
b.tap_image("harvestallcrops.png", threshold=0.8)
```

Robust pattern: wait → act → verify
```python
import time
from bot import Bot

def main():
    b = Bot()
    # Wait then act
    if b.wait_for_image("mainmenumyfarm.png", threshold=0.8, timeout=20, click_on_appear=True):
        time.sleep(0.5)
        if b.tap_image("harvestallcrops.png", threshold=0.8):
            # Verify disappearance
            deadline = time.time() + 10
            while time.time() < deadline:
                _, rects = b.match_template("harvestallcrops.png", threshold=0.75, return_image=False)
                if len(rects) == 0:
                    break
                time.sleep(0.3)
```

Branching by detection
```python
_, rects = b.match_template("plantall.png", threshold=0.75, return_image=False)
if len(rects) > 0:
    b.tap_image("plantall.png", threshold=0.75)
else:
    b.swipe(200, 1200, 900, 1200, 300)
```

Reading values (OCR)
```python
gold = b.read_number_near_template("mainmenumyfarm.png", (80, 0, 200, 80), threshold=0.7, number_type="int")
print("gold:", gold)
```

Run flows
- Scripted flow: python main.py runpy examples/my_flow.py
- See examples:
  - [examples/my_flow.py](../examples/my_flow.py)
  - [examples/advanced_flow.py](../examples/advanced_flow.py)
  - Doc: [examples/workflow.md](../examples/workflow.md)

Guidelines
- Keep templates tight and unique; avoid dynamic text regions.
- Use small sleeps (0.2–0.5s) after taps before verifying.
- Prefer wait_for_image(..., click_on_appear=True) over blind tap loops.
- Log decisions and outcomes to stdout for CI visibility.