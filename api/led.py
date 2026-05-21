#!/usr/bin/env python3
"""Slow rainbow pulse for a single NeoPixel on GPIO 18."""

import time
import math
from rpi_ws281x import PixelStrip, Color

LED_PIN = 18
CYCLE_SECONDS = 12  # time for a full rainbow loop
PULSE_SECONDS = 3   # breathing pulse speed

strip = PixelStrip(1, LED_PIN, brightness=255)
strip.begin()

def hsv_to_rgb(h, s, v):
    """h in [0,1), s in [0,1], v in [0,1] -> (r, g, b) ints 0-255."""
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i %= 6
    if i == 0: r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    else: r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)

try:
    while True:
        t = time.time()
        hue = (t / CYCLE_SECONDS) % 1.0
        # Pulse brightness between 0.35 and 1.0 using a sine wave
        pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / PULSE_SECONDS))
        r, g, b = hsv_to_rgb(hue, 1.0, pulse)
        strip.setPixelColor(0, Color(r, g, b))
        strip.show()
        time.sleep(0.02)
except KeyboardInterrupt:
    strip.setPixelColor(0, Color(0, 0, 0))
    strip.show()
