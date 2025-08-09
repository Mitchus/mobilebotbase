"""
Example automation flow using the Bot API.
Run: python main.py runpy examples/my_flow.py
"""
import time
from bot import Bot


def main():
    b = Bot()
    caught = 0
    while caught < 42069:
        # Wait for farmpongfish2.png and spam click it 3 times
        b.wait_for_image("farmpongfish2.png", threshold=0.55, timeout=20, click_on_appear=True)
        for _ in range(2):
            b.click_last_match()
            time.sleep(0.01)
        # if catchingfish.png press catchingfish
        time.sleep(0.1)
        b.tap_image("catchingfish.png", threshold=0.7, clicks=10)
        time.sleep(0.1)
        if b.match_template("youcaughtsomething.png"):
            # todo
            caught += 1 
        else:
            print("No catch this time.")

if __name__ == "__main__":
    main()
