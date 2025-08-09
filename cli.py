import argparse
import sys
from typing import Optional

from bot import Bot, ensure_img_dir


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(description="ADB Image Bot CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # basic input
    p_click = sub.add_parser("click", help="Tap at screen coordinates")
    p_click.add_argument("x", type=int)
    p_click.add_argument("y", type=int)

    p_swipe = sub.add_parser("swipe", help="Swipe from (x1,y1) to (x2,y2) in duration ms")
    p_swipe.add_argument("x1", type=int)
    p_swipe.add_argument("y1", type=int)
    p_swipe.add_argument("x2", type=int)
    p_swipe.add_argument("y2", type=int)
    p_swipe.add_argument("duration", type=int)

    # find / wait
    p_find = sub.add_parser("find", help="Find template; optionally click first match")
    p_find.add_argument("template", type=str)
    p_find.add_argument("--threshold", type=float, default=0.45)
    p_find.add_argument("--click", action="store_true")
    p_find.add_argument("--show", action="store_true", help="Show a preview window with matches drawn")

    p_wait = sub.add_parser("wait", help="Wait for template; optionally click on appear")
    p_wait.add_argument("template", type=str)
    p_wait.add_argument("--threshold", type=float, default=0.45)
    p_wait.add_argument("--timeout", type=float, default=30.0)
    p_wait.add_argument("--click", action="store_true")

    # capture
    p_cap = sub.add_parser("capture", help="Interactively capture a new template image into img/")
    p_cap.add_argument("out_name", type=str, help="Filename to save under img/. e.g. market.png")
    p_cap.add_argument("--overwrite", action="store_true")
    p_cap.add_argument("--preview", action="store_true", help="Show a preview of the saved crop")

    # run python script that uses Bot API
    p_runpy = sub.add_parser("runpy", help="Run a Python script that uses bot.Bot API")
    p_runpy.add_argument("script", type=str)
    p_runpy.add_argument("script_args", nargs=argparse.REMAINDER, help="Args passed through to the script")

    # coordinate probe
    p_coords = sub.add_parser("coords", help="Open a screenshot viewer that shows coordinates under the mouse")
    p_coords.add_argument("--scale", type=float, default=1.0, help="Display scale factor (1.0 = native)")

    # OCR: read number
    p_readnum = sub.add_parser("readnum", help="Read a number by OCR either in an ROI or near a template")
    mode = p_readnum.add_mutually_exclusive_group(required=True)
    mode.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"), help="ROI in device pixels")
    mode.add_argument("--near", nargs=5, metavar=("TEMPLATE", "DX", "DY", "W", "H"), help="Read near template: path and ROI offset")
    p_readnum.add_argument("--type", choices=["int", "float"], default="int", help="Parse as int or float")
    p_readnum.add_argument("--threshold", type=float, default=0.45, help="Template match threshold when using --near")
    p_readnum.add_argument("--psm", type=int, default=7, help="Tesseract page segmentation mode (default 7)")
    p_readnum.add_argument("--invert", action="store_true", help="Invert colors before OCR (use for light-on-dark or vice versa)")

    args = parser.parse_args(argv)

    if args.cmd == "click":
        bot = Bot()
        bot.click(args.x, args.y)
        return 0

    if args.cmd == "swipe":
        bot = Bot()
        bot.swipe(args.x1, args.y1, args.x2, args.y2, args.duration)
        return 0

    if args.cmd == "find":
        bot = Bot()
        img, rects = bot.match_template(args.template, threshold=args.threshold, return_image=args.show)
        print(rects)
        if args.click and len(rects) > 0:
            cx = int((rects[0][0] + rects[0][2]) / 2)
            cy = int((rects[0][1] + rects[0][3]) / 2)
            bot.click(cx, cy)
        if args.show:
            try:
                import cv2  # lazy import
                cv2.namedWindow("Matches", cv2.WINDOW_NORMAL)
                cv2.imshow("Matches", img)
                cv2.waitKey(500)
                cv2.destroyWindow("Matches")
            except Exception:
                pass
        return 0

    if args.cmd == "wait":
        bot = Bot()
        ok = bot.wait_for_image(args.template, threshold=args.threshold, timeout=args.timeout, click_on_appear=args.click)
        return 0 if ok else 1

    if args.cmd == "capture":
        ensure_img_dir()
        bot = Bot()
        out = bot.capture_template(args.out_name, overwrite=args.overwrite, show_preview=args.preview)
        print(out)
        return 0

    if args.cmd == "runpy":
        # Execute a Python script in this process so it can import bot and use Bot()
        import runpy as _runpy
        # Prepend extra args for the script to sys.argv
        sys.argv = [args.script] + (args.script_args or [])
        _runpy.run_path(args.script, run_name="__main__")
        return 0

    if args.cmd == "coords":
        # Interactive viewer that shows device coordinates in the window status bar (no drawing on the image).
        import os
        import time
        try:
            import cv2  # type: ignore
        except Exception:  # pragma: no cover
            print("OpenCV is required for this command. Install with: pip install opencv-python")
            return 2

        bot = Bot()

        scale = max(0.05, float(args.scale))
        win = "Coords (q=quit, r=refresh, s=save, click=print coords)"

        def grab():
            return bot.screenshot()

        base = grab()

        def render(img):
            disp = img
            if abs(scale - 1.0) > 1e-6:
                h, w = img.shape[:2]
                disp = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            return disp

        # Try to create a GUI window; fall back gracefully if GUI support is unavailable
        try:
            cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        except Exception as e:  # pragma: no cover
            print("OpenCV GUI functions are unavailable in this environment.")
            print("Tip: Install a GUI-enabled OpenCV (pip install opencv-python) and ensure a display is available.")
            print("Headless alternative: run 'python main.py find catchingfish.png --threshold 0.7' to print match rectangles;\n"
                  "use the printed (x1,y1,x2,y2) to derive a CATCH_ROI around that area.")
            return 2

        def show_status(text: str, ms: int = 1000) -> None:
            # Prefer status bar; fall back to window title if unavailable
            try:
                cv2.displayStatusBar(win, text, ms)
            except Exception:  # pragma: no cover
                try:
                    cv2.setWindowTitle(win, f"{win} — {text}")
                except Exception:
                    pass

        def on_mouse(event, x, y, flags, param):  # noqa: ARG001
            dx = int(x / scale)
            dy = int(y / scale)
            show_status(f"{dx}, {dy}", 1000)
            if event == cv2.EVENT_LBUTTONDOWN:
                print(f"click: {dx} {dy}")

        cv2.setMouseCallback(win, on_mouse)

        while True:
            disp = render(base)
            cv2.imshow(win, disp)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):  # q or ESC
                break
            elif key == ord("r"):
                base = grab()
            elif key == ord("s"):
                ts = time.strftime("%Y%m%d_%H%M%S")
                os.makedirs("img", exist_ok=True)
                path = os.path.join("img", f"coords_{ts}.png")
                cv2.imwrite(path, base)
                print(f"saved {path}")

        cv2.destroyWindow(win)
        return 0

    if args.cmd == "readnum":
        bot = Bot()
        try:
            if args.roi is not None:
                x, y, w, h = map(int, args.roi)
                val = bot.read_number_in_roi((x, y, w, h), number_type=args.type, psm=args.psm, invert=args.invert)
            else:
                tpl, dx, dy, w, h = args.near
                val = bot.read_number_near_template(tpl, (int(dx), int(dy), int(w), int(h)), threshold=args.threshold, number_type=args.type, psm=args.psm, invert=args.invert)
        except RuntimeError as e:
            print(str(e))
            return 2
        if val is None:
            print("None")
            return 1
        print(val)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
