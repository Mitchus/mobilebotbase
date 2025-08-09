"""
Example automation flow using the Bot API.
Run: python main.py runpy examples/my_flow.py
"""
import time
from bot import Bot


def main():
    b = Bot()

    b.wait_for_image("mainmenumyfarm.png", threshold=0.8, timeout=20, click_on_appear=True)
    time.sleep(1.0)

    b.tap_image("harvestallcrops.png", threshold=0.8)
    time.sleep(0.5)

    


if __name__ == "__main__":
    main()
