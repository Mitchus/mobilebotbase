# Templates and Matching Tips

Where templates live
- Put PNGs under img/. Pass bare names; [`bot.Bot`](../bot.py) auto-prefixes.

Capturing templates
- Interactive capture: python main.py capture my_button.png
  - Optionally add --preview or --overwrite.
  - See [`bot.Bot.capture_template`](../bot.py).

Picking good crops
- Crop the smallest distinctive region (icon edges, high-contrast shapes).
- Avoid dynamic text, shadows, timers, or animated areas.
- Consider separate variants (day/night): my_button_day.png, my_button_night.png.

Threshold tuning
- Start at 0.6–0.8. Increase to reduce false positives; decrease to catch subtle matches.
- Use: python main.py find harvestallcrops.png --threshold 0.8 --show
- If getting multiple close rectangles, your crop may be too generic; recapture tighter.

Interpreting results
- [`bot.Bot.match_template`](../bot.py) returns Nx4 rects [x1,y1,x2,y2].
- Center point helper used internally: [`bot.rect_center`](../bot.py).

Performance notes
- Matching is against full screenshot per call.
- Prefer verifying existence with slightly higher thresholds to reduce retries.