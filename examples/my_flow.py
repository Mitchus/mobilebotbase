"""
Example automation flow using the Bot API.
Run: python main.py runpy examples/my_flow.py
"""
import time
from bot import Bot


def main():
    b = Bot()
    caught = 0
    CATCH_ROI = (0, 1800, 1000, 200)
    while True:
        # 1) Wait and burst-click the fish
        b.wait_for_image(
            "farmpongfish2.png",
            threshold=0.9,
            timeout=20,
            click_on_appear=True,
            click_on_appear_clicks=3,
            inter_click_delay=0.0,
            use_gray=False,)
        if b.wait_for_image("incapturefish.png", 0.8, timeout= 1):
            for i in range(5):
                b.tap_image("catchingfish.png")

if __name__ == "__main__":
    main()
