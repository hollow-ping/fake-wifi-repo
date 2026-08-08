#!/usr/bin/env python3
"""
Status LEDs for Fake WiFi (GPIO18, up to 4 NeoPixels).

1. BOOT_DELAY — AP boot wait (AP_BOOT_DELAY_SECS): all LEDs flashing red.
2. OFF_AIR   — Pi on, BURNER-NET.COM not broadcasting: all LEDs solid red.
3. ONBOARD   — Broadcasting on onboard radio: green bounce 4s, then rainbow glow 4s (8s loop).
4. USB       — Broadcasting via USB dongle: white bounce 4s, then rainbow glow 4s (8s loop).

Broadcasting = uap0 present with 192.168.4.1, hostapd + dnsmasq active.
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
    from rpi_ws281x import Color, PixelStrip, ws
except ImportError:
    print("rpi_ws281x not installed; run: sudo apt install python3-rpi-ws281x", file=sys.stderr)
    sys.exit(1)

LED_PIN = 18
LED_COUNT = 4
MAX_BRIGHTNESS = int(os.environ.get("FAKE_WIFI_LED_BRIGHTNESS", "64"))  # ~25%

# This strip's wire order is RGB, not the library's WS2812 default (GRB) —
# confirmed via pi/led-color-test.py (sending red showed green and vice versa).
# Override with FAKE_WIFI_LED_STRIP_TYPE=GRB (etc.) if you swap to a different strip.
_STRIP_TYPE_NAME = os.environ.get("FAKE_WIFI_LED_STRIP_TYPE", "RGB").strip().upper()
STRIP_TYPE = getattr(ws, f"WS2811_STRIP_{_STRIP_TYPE_NAME}", ws.WS2811_STRIP_RGB)

AP_PHY_FILE = "/run/fake-wifi/ap-phy"
AP_IFACE_FILE = "/run/fake-wifi/ap-iface"
BOOT_DELAY_FLAG = "/run/fake-wifi/ap-boot-delay"
POLL_INTERVAL = 0.5
FRAME_INTERVAL = 0.02
RESYNC_INTERVAL = 3.0  # repaint an unchanged frame this often, to clear glitched pixels

CYCLE_SEC = 8.0
BOUNCE_SEC = 4.0
RAINBOW_SEC = 4.0
BOUNCE_STEP_SEC = 0.1  # ~6–7 round trips across 4 LEDs in 4s
RAINBOW_PULSE_SEC = 2.0
BOOT_DELAY_FLASH_SEC = 0.8

OFF_AIR_RGB = (255, 0, 0)
GREEN_RGB = (0, 255, 0)
WHITE_RGB = (255, 255, 255)


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


def read_ap_iface() -> str:
    try:
        with open(AP_IFACE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def iface_has_ap_ip(iface: str) -> bool:
    if not iface or not os.path.isdir(f"/sys/class/net/{iface}"):
        return False
    try:
        out = subprocess.run(
            ["ip", "-4", "-br", "addr", "show", iface],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
    except (subprocess.TimeoutExpired, OSError):
        return False
    return "192.168.4.1" in out


def is_broadcasting() -> bool:
    iface = read_ap_iface()
    if not iface:
        # Legacy: dual-radio used uap0 only
        iface = "uap0" if uap0_exists() else ""
    if not iface or not iface_has_ap_ip(iface):
        return False
    hostapd_ok = (
        service_active_state("hostapd") == "active"
        or bool(run(["pgrep", "-x", "hostapd"]))
    )
    dnsmasq_ok = (
        service_active_state("dnsmasq") == "active"
        or bool(run(["pgrep", "-x", "dnsmasq"]))
    )
    return hostapd_ok and dnsmasq_ok


def evaluate_mode() -> LedMode:
    if is_boot_delay():
        return LedMode.BOOT_DELAY
    if not is_broadcasting():
        return LedMode.OFF_AIR
    if is_usb_phy(read_ap_phy()):
        return LedMode.USB
    return LedMode.ONBOARD


def boot_delay_flash_on(t: float) -> bool:
    phase = t % BOOT_DELAY_FLASH_SEC
    return phase < BOOT_DELAY_FLASH_SEC / 2


def bounce_index(t_in_bounce: float) -> int:
    """Ping-pong index across 0..LED_COUNT-1."""
    if LED_COUNT <= 1:
        return 0
    path_len = 2 * (LED_COUNT - 1)  # e.g. 0,1,2,3,2,1
    step = int(t_in_bounce / BOUNCE_STEP_SEC) % path_len
    if step < LED_COUNT:
        return step
    return path_len - step


def frame_bounce(t_in_bounce: float, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    idx = bounce_index(t_in_bounce)
    return [color if i == idx else (0, 0, 0) for i in range(LED_COUNT)]


def frame_rainbow_glow(t_in_rainbow: float) -> list[tuple[int, int, int]]:
    """All LEDs same slowly shifting hue, soft brightness pulse."""
    hue = (t_in_rainbow / RAINBOW_SEC) % 1.0
    pulse = 0.35 + 0.65 * (
        0.5 + 0.5 * math.sin(t_in_rainbow * 2 * math.pi / RAINBOW_PULSE_SEC)
    )
    rgb = hsv_to_rgb(hue, 1.0, pulse)
    return [rgb] * LED_COUNT


def frame_broadcast(t: float, bounce_color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    phase = t % CYCLE_SEC
    if phase < BOUNCE_SEC:
        return frame_bounce(phase, bounce_color)
    return frame_rainbow_glow(phase - BOUNCE_SEC)


def render_frame(mode: LedMode, t: float) -> list[tuple[int, int, int]]:
    if mode == LedMode.BOOT_DELAY:
        if boot_delay_flash_on(t):
            return [OFF_AIR_RGB] * LED_COUNT
        return [(0, 0, 0)] * LED_COUNT
    if mode == LedMode.OFF_AIR:
        return [OFF_AIR_RGB] * LED_COUNT
    if mode == LedMode.ONBOARD:
        return frame_broadcast(t, GREEN_RGB)
    return frame_broadcast(t, WHITE_RGB)


def main() -> None:
    strip = PixelStrip(LED_COUNT, LED_PIN, brightness=MAX_BRIGHTNESS, strip_type=STRIP_TYPE)
    strip.begin()

    mode = LedMode.OFF_AIR
    last_poll = 0.0
    last_pixels: list[tuple[int, int, int]] | None = None
    last_push = 0.0

    try:
        while True:
            now = time.time()
            if now - last_poll >= POLL_INTERVAL:
                mode = evaluate_mode()
                last_poll = now

            pixels = render_frame(mode, now)
            # Every write to the strip is a chance for a bit error to latch a wrong
            # colour, so skip writes that would not change anything. RESYNC_INTERVAL
            # still repaints periodically to clear any pixel that did glitch.
            if pixels != last_pixels or now - last_push >= RESYNC_INTERVAL:
                for i, (r, g, b) in enumerate(pixels):
                    strip.setPixelColor(i, Color(r, g, b))
                strip.show()
                last_pixels = pixels
                last_push = now
            time.sleep(FRAME_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()


if __name__ == "__main__":
    main()
