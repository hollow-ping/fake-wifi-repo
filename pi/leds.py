#!/usr/bin/env python3
"""
Status LEDs for Fake WiFi (GPIO18, up to 4 NeoPixels).

1. BOOT_DELAY — AP boot wait (AP_BOOT_DELAY_SECS): all LEDs flashing red.
2. OFF_AIR   — Pi on, BURNERNET not broadcasting: all LEDs solid red.
3. ONBOARD   — Broadcasting on onboard radio (not USB): rainbow + LED 0 red blip / 3s.
4. USB       — Broadcasting via USB dongle: rainbow only.

Broadcasting = uap0 present, hostapd + dnsmasq active.
USB vs onboard comes from /run/fake-wifi/ap-phy (same phy start-ap.sh chose).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from enum import Enum, auto

try:
    from rpi_ws281x import Color, PixelStrip
except ImportError:
    print("rpi_ws281x not installed; run: sudo apt install python3-rpi-ws281x", file=sys.stderr)
    sys.exit(1)

LED_PIN = 18
LED_COUNT = 4
MAX_BRIGHTNESS = int(os.environ.get("FAKE_WIFI_LED_BRIGHTNESS", "64"))  # ~25%

AP_PHY_FILE = "/run/fake-wifi/ap-phy"
BOOT_DELAY_FLAG = "/run/fake-wifi/ap-boot-delay"
POLL_INTERVAL = 0.5
FRAME_INTERVAL = 0.02

RAINBOW_CYCLE_SEC = 12.0
HUE_SPACING = 0.22
ONBOARD_BLIP_INTERVAL = 3.0
ONBOARD_BLIP_SEC = 0.12
BOOT_DELAY_FLASH_SEC = 0.8

OFF_AIR_RGB = (255, 0, 0)


class LedMode(Enum):
    BOOT_DELAY = auto()
    OFF_AIR = auto()
    ONBOARD = auto()
    USB = auto()


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i %= 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=3, check=False
        ).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def service_active_state(unit: str) -> str:
    out = run(["systemctl", "show", unit, "-p", "ActiveState", "--value"])
    return out or "unknown"


def uap0_exists() -> bool:
    return os.path.isdir("/sys/class/net/uap0")


def is_boot_delay() -> bool:
    return os.path.isfile(BOOT_DELAY_FLAG)


def read_ap_phy() -> str:
    try:
        with open(AP_PHY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_usb_phy(iface: str) -> bool:
    """True if iface is a USB wlan (matches start-ap.sh is_usb_wlan)."""
    if not iface or not os.path.isdir(f"/sys/class/net/{iface}"):
        return False
    device = f"/sys/class/net/{iface}/device"
    if not os.path.exists(device):
        return False
    try:
        subsystem = os.path.realpath(os.path.join(device, "subsystem"))
    except OSError:
        return False
    return "usb" in subsystem


def is_broadcasting() -> bool:
    if not uap0_exists():
        return False
    return (
        service_active_state("hostapd") == "active"
        and service_active_state("dnsmasq") == "active"
    )


def evaluate_mode() -> LedMode:
    if is_boot_delay():
        return LedMode.BOOT_DELAY
    if not is_broadcasting():
        return LedMode.OFF_AIR
    if is_usb_phy(read_ap_phy()):
        return LedMode.USB
    return LedMode.ONBOARD


def rainbow_brightness(t: float) -> float:
    return 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / (RAINBOW_CYCLE_SEC / 2)))


def onboard_blip_active(t: float) -> bool:
    return (t % ONBOARD_BLIP_INTERVAL) < ONBOARD_BLIP_SEC


def boot_delay_flash_on(t: float) -> bool:
    phase = t % BOOT_DELAY_FLASH_SEC
    return phase < BOOT_DELAY_FLASH_SEC / 2


def frame_rainbow(t: float, onboard_blip: bool) -> list[tuple[int, int, int]]:
    base_hue = (t / RAINBOW_CYCLE_SEC) % 1.0
    pulse = rainbow_brightness(t)
    pixels: list[tuple[int, int, int]] = []
    for i in range(LED_COUNT):
        if i == 0 and onboard_blip and onboard_blip_active(t):
            pixels.append(OFF_AIR_RGB)
            continue
        hue = (base_hue + i * HUE_SPACING) % 1.0
        pixels.append(hsv_to_rgb(hue, 1.0, pulse))
    return pixels


def render_frame(mode: LedMode, t: float) -> list[tuple[int, int, int]]:
    if mode == LedMode.BOOT_DELAY:
        if boot_delay_flash_on(t):
            return [OFF_AIR_RGB] * LED_COUNT
        return [(0, 0, 0)] * LED_COUNT
    if mode == LedMode.OFF_AIR:
        return [OFF_AIR_RGB] * LED_COUNT
    return frame_rainbow(t, onboard_blip=(mode == LedMode.ONBOARD))


def main() -> None:
    strip = PixelStrip(LED_COUNT, LED_PIN, brightness=MAX_BRIGHTNESS)
    strip.begin()

    mode = LedMode.OFF_AIR
    last_poll = 0.0

    try:
        while True:
            now = time.time()
            if now - last_poll >= POLL_INTERVAL:
                mode = evaluate_mode()
                last_poll = now

            pixels = render_frame(mode, now)
            for i, (r, g, b) in enumerate(pixels):
                strip.setPixelColor(i, Color(r, g, b))
            strip.show()
            time.sleep(FRAME_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()


if __name__ == "__main__":
    main()
