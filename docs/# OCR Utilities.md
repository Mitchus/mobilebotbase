# OCR Utilities

Requirements
- Python package: pytesseract
- System binary: tesseract (on Linux: apt-get install -y tesseract-ocr)

APIs
- [`bot.Bot.read_text_in_roi`](../bot.py)
  - Reads raw text from ROI. Params: roi=(x,y,w,h), psm, whitelist, invert.

- [`bot.Bot.read_number_in_roi`](../bot.py)
  - Parses first number in ROI. number_type="int" or "float".

- [`bot.Bot.read_number_near_template`](../bot.py)
  - Finds template then OCRs a nearby ROI via offset=(dx,dy,w,h) from the match top-left.

CLI shortcuts
- ROI: python main.py readnum --roi X Y W H --type int|float [--psm 7] [--invert]
- Near template: python main.py readnum --near TEMPLATE DX DY W H --threshold 0.7 --type float

Tips
- If text is light-on-dark (or vice versa), try --invert or invert=True.
- Experiment with psm values (6, 7, 8) for single-line vs block text.
- Use coords to measure ROIs precisely.

Example
```python
from bot import Bot
b = Bot()
price = b.read_number_near_template("mainmenumyfarm.png", (80, 0, 200, 80), threshold=0.7, number_type="float", psm=6)
print(price)
```