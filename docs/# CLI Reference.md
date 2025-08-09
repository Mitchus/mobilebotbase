# CLI Reference

Entry point: [main.py](../main.py) delegates to [cli.py](../cli.py)

General
- Help: python main.py --help

Commands
- click
  - Usage: python main.py click X Y
  - Calls [`bot.Bot.click`](../bot.py).

- swipe
  - Usage: python main.py swipe X1 Y1 X2 Y2 DURATION_MS
  - Calls [`bot.Bot.swipe`](../bot.py).

- find
  - Usage: python main.py find TEMPLATE --threshold 0.6 [--click] [--show]
  - Prints matches as an Nx4 array. If --click, taps center of first match.
  - --show opens a preview window with rectangles.

- wait
  - Usage: python main.py wait TEMPLATE --threshold 0.6 --timeout 20 [--click]
  - Returns 0 on success, 1 on timeout.

- capture
  - Usage: python main.py capture out_name.png [--overwrite] [--preview]
  - Interactive ROI selection; saves under img/.

- runpy
  - Usage: python main.py runpy path/to/script.py -- [args...]
  - Executes your Python script in-process so it can import [`bot.Bot`](../bot.py).

- coords
  - Usage: python main.py coords [--scale 0.8]
  - Interactive screenshot viewer. Keys: q/ESC quit, r refresh, s save.
  - Left click prints “click: X Y” to stdout.

- readnum
  - ROI mode: python main.py readnum --roi X Y W H --type int|float [--psm 7] [--invert]
  - Near-template mode: python main.py readnum --near TEMPLATE DX DY W H --threshold 0.7 --type int|float [--psm 7] [--invert]
  - Exit codes: 0 print value, 1 print "None", 2 runtime error.

Tips
- Combine find --show for tuning thresholds.
- Use coords to measure ROIs for OCR or swipes.