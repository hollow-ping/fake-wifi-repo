#!/usr/bin/env python3
"""One-off test: cycles pure R, G, B on all pixels so we can see the strip's
actual wire color order vs what the code sends. Run with:
  sudo systemctl stop fake-wifi-leds
  sudo python3 led-color-test.py
  sudo systemctl start fake-wifi-leds   # when done
"""
import time
from rpi_ws281x import PixelStrip, Color, ws

strip = PixelStrip(4, 18, brightness=80, strip_type=ws.WS2811_STRIP_RGB)
strip.begin()


def show(r, g, b, label, secs=4):
    print(f"Showing {label}: sent R={r} G={g} B={b} for {secs}s", flush=True)
    for i in range(4):
        strip.setPixelColor(i, Color(r, g, b))
    strip.show()
    time.sleep(secs)


show(255, 0, 0, "RED (255,0,0)")
show(0, 255, 0, "GREEN (0,255,0)")
show(0, 0, 255, "BLUE (0,0,255)")

for i in range(4):
    strip.setPixelColor(i, Color(0, 0, 0))
strip.show()
print("done")
