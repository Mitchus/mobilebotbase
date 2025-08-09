Video stream matching demo

This folder contains a live video matcher that finds a template (e.g., img/catchingfish.png) on a continuous device stream and reports the location in real time. It’s useful to evaluate latency and robustness vs the screencap-based approach.

What it does
- Captures frames from one of these sources:
	- adb exec-out screenrecord (H.264) decoded with PyAV (default)
	- scrcpy via a v4l2 loopback device (robust with OpenCV)
	- A local video file or webcam device
- Matches the template on every frame and either prints coordinates (headless) or overlays a marker (GUI).

Requirements
- Android platform tools (adb) and a connected device (adb devices).
- Python deps in your venv:
	- pip install av opencv-python numpy
- scrcpy if you plan to use the scrcpy + v4l2 route.
- For GUI overlays: a desktop that supports OpenCV highgui windows. On Wayland, you may need QT_QPA_PLATFORM=xcb.

Script reference
- Entrypoint: stream_tests/stream_match.py
- Key flags:
	- --template PATH            Template image to match (e.g., img/catchingfish.png)
	- --threshold FLOAT          Match threshold (default 0.7)
	- --gray                     Use grayscale matching (faster)
	- --source SRC               One of: adb (default), scrcpy, video:/path, cam:N
	- --size WIDTHxHEIGHT        For adb source (downscale at source, e.g., 1280x720)
	- --bit-rate BPS             For adb/scrcpy streaming (e.g., 8000000)
	- --gui                      Show a window and overlay marker/box; otherwise print match lines

Quick starts

1) ADB screenrecord (headless; recommended to start)
```sh
source venv/bin/activate
python stream_tests/stream_match.py \
	--template img/catchingfish.png \
	--threshold 0.7 \
	--gray \
	--source adb \
	--size 1280x720 \
	--bit-rate 8000000
```
Expected: prints lines like: `match: x1 y1 x2 y2 center=(cx,cy)` while the template is visible.

2) scrcpy via v4l2 loopback (stable with OpenCV)
- Install and load the loopback module (Arch example):
```sh
sudo pacman -S --needed linux-headers dkms v4l2loopback-dkms
sudo modprobe v4l2loopback devices=1 video_nr=10 card_label='scrcpy' exclusive_caps=1
ls -l /dev/video10
```
- Start scrcpy streaming to the loopback device:
```sh
scrcpy --no-audio --no-control --no-display --bit-rate 8000000 --v4l2-sink=/dev/video10
```
- In another terminal, run the matcher on the loopback device:
```sh
source venv/bin/activate
python stream_tests/stream_match.py --template img/catchingfish.png --threshold 0.7 --gray --source video:/dev/video10
```

3) Local file or webcam
```sh
# From a recorded file
python stream_tests/stream_match.py --template img/catchingfish.png --source video:out.mkv --threshold 0.7 --gray

# From a webcam device
python stream_tests/stream_match.py --template img/catchingfish.png --source cam:0 --threshold 0.7 --gray
```

Optional GUI overlay
- If your desktop supports OpenCV windows, add --gui to see a live window with a marker and status text:
```sh
QT_QPA_PLATFORM=xcb python stream_tests/stream_match.py --template img/catchingfish.png --source adb --size 1280x720 --gray --gui
```
Tip: On Wayland, QT_QPA_PLATFORM=xcb avoids missing “wayland” plugin errors. If GUI still fails, run headless (default) — it will print coordinates instead.

Troubleshooting
- PyAV InvalidDataError with scrcpy stdout (record pipe):
	- Some builds don’t produce a clean container on stdout. Prefer the v4l2 loopback sink (see option 2 above), or use adb source.
- OpenCV GUI errors on Wayland:
	- Use QT_QPA_PLATFORM=xcb, or skip --gui to run headless.
- v4l2loopback module not found (modprobe fails):
	- Install matching kernel headers and v4l2loopback-dkms (Arch: linux-headers dkms v4l2loopback-dkms; LTS: linux-lts-headers).
- Permissions for /dev/video10:
	- You may need to add your user to the video group or `sudo chgrp video /dev/video10 && sudo chmod g+rw /dev/video10`.

Tuning tips
- Use --gray to reduce compute per frame.
- Reduce source size (e.g., 960x540) for higher FPS.
- Raise/lower --threshold to adjust sensitivity.

Notes
- This is a lab tool to evaluate latency vs. screencap-based detection — keep it simple and headless for best performance.
