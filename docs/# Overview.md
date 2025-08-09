# Overview

Purpose
- Automate Android UI flows by detecting small template images on the screen and sending input events via ADB.

Architecture
- Device I/O: ADB shell for input; ADB screencap for screenshots. See [`bot.Bot.click`](../bot.py), [`bot.Bot.swipe`](../bot.py), [`bot.Bot.screenshot`](../bot.py).
- Vision: OpenCV-based template match. See [`bot.Bot.match_template`](../bot.py) and helpers like [`bot.draw_rectangles`](../bot.py).
- High-level actions: [`bot.Bot.tap_image`](../bot.py), [`bot.Bot.wait_for_image`](../bot.py).
- Utilities: Template capture tooling, OCR for reading numbers or free text. See [`bot.Bot.capture_template`](../bot.py), [`bot.Bot.read_number_in_roi`](../bot.py), [`bot.Bot.read_text_in_roi`](../bot.py).

Typical flow
1) Wait for a known screen or button to appear.
2) Tap the element or perform a swipe.
3) Verify the outcome (element appears/disappears, number changes).
4) Repeat or branch.

See examples:
- [examples/my_flow.py](../examples/my_flow.py)
- [examples/advanced_flow.py](../examples/advanced_flow.py)