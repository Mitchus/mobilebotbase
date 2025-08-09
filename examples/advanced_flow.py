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
