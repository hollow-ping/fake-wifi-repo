#!/usr/bin/env python3
"""
Status LEDs for Fake WiFi (GPIO18, up to 4 NeoPixels).

1. BOOT_DELAY — AP boot wait: pixel 1 flashing red, half level.
2. STARTING   — start-ap.sh mid-run: pixel 1 flashing green, half level.
3. OFF_AIR    — AP not running or failed: all LEDs solid red.
4. ONBOARD    — Up on onboard radio, no clients: green bounce (1s/pixel).
5. USB        — Up on USB radio, no clients: blue bounce (1s/pixel).
6. CONNECTED  — Client associated (not in portal "connecting"): LEDs 1–3 solid
                dim green, LED 4 blinks blue 1s on / 1s off.
7. CONNECTING — Guest is on a connect-flow page (go/queue/geolocate/…): rainbow.

"Connecting" is signaled by the portal via POST /api/led-portal (file under
/var/lib/burnernet). Wi‑Fi association alone cannot see which HTML page is open.
Every frame goes through limit_current() — the strip shares the Pi's 5V rail.
"""

from __future__ import annotations

import json
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
# Per-state levels are chosen in software (HALF vs dim), so leave the hardware
# scale wide open and let limit_current() be the thing that bounds draw.
MAX_BRIGHTNESS = int(os.environ.get("FAKE_WIFI_LED_BRIGHTNESS", "255"))
HALF = 128
# Connected solids — intentionally dimmer than half to keep 5V headroom.
CONNECTED_GREEN_LEVEL = int(os.environ.get("FAKE_WIFI_LED_CONNECTED_GREEN", "64"))

# The strip is fed from the Pi's own 5V pin, so its draw competes with the SoC and
# the radio. Cap estimated draw per frame. ~20mA is one WS2812B channel at full.
MA_PER_CHANNEL_FULL = 20.0
CURRENT_BUDGET_MA = float(os.environ.get("FAKE_WIFI_LED_BUDGET_MA", "50"))

# This strip's wire order is RGB, not the library's WS2812 default (GRB).
_STRIP_TYPE_NAME = os.environ.get("FAKE_WIFI_LED_STRIP_TYPE", "RGB").strip().upper()
STRIP_TYPE = getattr(ws, f"WS2811_STRIP_{_STRIP_TYPE_NAME}", ws.WS2811_STRIP_RGB)

AP_PHY_FILE = "/run/fake-wifi/ap-phy"
AP_IFACE_FILE = "/run/fake-wifi/ap-iface"
BOOT_DELAY_FLAG = "/run/fake-wifi/ap-boot-delay"
STARTING_FLAG = "/run/fake-wifi/ap-starting"
LED_PORTAL_FILE = os.environ.get(
    "FAKE_WIFI_LED_PORTAL_FILE", "/var/lib/burnernet/led-portal.json"
)
# Portal heartbeats every ~2.5s; treat as connecting if fresher than this.
PORTAL_CONNECTING_TTL_SEC = float(os.environ.get("FAKE_WIFI_LED_PORTAL_TTL", "8"))

AP_UNITS = ("fake-wifi-ap.service", "fake-wifi-ap-manual.service")
POLL_INTERVAL = 0.5
FRAME_INTERVAL = 0.02
RESYNC_INTERVAL = 3.0

BOUNCE_STEP_SEC = 1.0
FLASH_PERIOD_SEC = 0.8
BLUE_BLINK_PERIOD_SEC = 2.0  # 1s on, 1s off
RAINBOW_CYCLE_SEC = 6.0

RED_HALF = (HALF, 0, 0)
GREEN_HALF = (0, HALF, 0)
BLUE_HALF = (0, 0, HALF)
RED_FULL = (255, 0, 0)
GREEN_CONNECTED = (0, CONNECTED_GREEN_LEVEL, 0)
BLACK = (0, 0, 0)


class LedMode(Enum):
    BOOT_DELAY = auto()
    STARTING = auto()
    OFF_AIR = auto()
    ONBOARD = auto()
    USB = auto()
    CONNECTED = auto()
    CONNECTING = auto()


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


def is_starting() -> bool:
    if os.path.isfile(STARTING_FLAG):
        return True
    return any(service_active_state(unit) == "activating" for unit in AP_UNITS)


def has_client() -> bool:
    iface = read_ap_iface() or ("uap0" if uap0_exists() else "")
    if not iface:
        return False
    return "Station " in run(["iw", "dev", iface, "station", "dump"])


def is_portal_connecting() -> bool:
    """True while a connect-flow page is heartbeating via /api/led-portal."""
    try:
        with open(LED_PORTAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("phase") != "connecting":
        return False
    try:
        ts = float(data.get("ts", 0))
    except (TypeError, ValueError):
        return False
    return (time.time() - ts) <= PORTAL_CONNECTING_TTL_SEC


def evaluate_mode() -> LedMode:
    if is_boot_delay():
        return LedMode.BOOT_DELAY
    if not is_broadcasting():
        return LedMode.STARTING if is_starting() else LedMode.OFF_AIR
    if is_portal_connecting():
        return LedMode.CONNECTING
    if has_client():
        return LedMode.CONNECTED
    if is_usb_phy(read_ap_phy()):
        return LedMode.USB
    return LedMode.ONBOARD


def flash_on(t: float, period: float = FLASH_PERIOD_SEC) -> bool:
    return t % period < period / 2


def frame_first_pixel_flash(t: float, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    lit = color if flash_on(t) else BLACK
    return [lit if i == 0 else BLACK for i in range(LED_COUNT)]


def bounce_index(t_in_bounce: float) -> int:
    if LED_COUNT <= 1:
        return 0
    path_len = 2 * (LED_COUNT - 1)
    step = int(t_in_bounce / BOUNCE_STEP_SEC) % path_len
    if step < LED_COUNT:
        return step
    return path_len - step


def frame_bounce(t: float, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    idx = bounce_index(t)
    return [color if i == idx else BLACK for i in range(LED_COUNT)]


def frame_connected(t: float) -> list[tuple[int, int, int]]:
    """LEDs 1–3 dim solid green; LED 4 blue blink 1s on / 1s off."""
    blue = BLUE_HALF if flash_on(t, BLUE_BLINK_PERIOD_SEC) else BLACK
    return [GREEN_CONNECTED, GREEN_CONNECTED, GREEN_CONNECTED, blue]


def frame_rainbow(t: float) -> list[tuple[int, int, int]]:
    """Fun rainbow while the guest is on a connecting screen."""
    base = (t / RAINBOW_CYCLE_SEC) % 1.0
    out: list[tuple[int, int, int]] = []
    for i in range(LED_COUNT):
        hue = (base + i / LED_COUNT) % 1.0
        out.append(hsv_to_rgb(hue, 1.0, 0.55))
    return out


def render_frame(mode: LedMode, t: float) -> list[tuple[int, int, int]]:
    if mode == LedMode.BOOT_DELAY:
        return frame_first_pixel_flash(t, RED_HALF)
    if mode == LedMode.STARTING:
        return frame_first_pixel_flash(t, GREEN_HALF)
    if mode == LedMode.OFF_AIR:
        return [RED_FULL] * LED_COUNT
    if mode == LedMode.CONNECTING:
        return frame_rainbow(t)
    if mode == LedMode.CONNECTED:
        return frame_connected(t)
    if mode == LedMode.USB:
        return frame_bounce(t, BLUE_HALF)
    return frame_bounce(t, GREEN_HALF)


def limit_current(pixels: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if CURRENT_BUDGET_MA <= 0:
        return pixels
    channels_lit = sum(sum(p) for p in pixels) / 255.0
    estimate_ma = channels_lit * MA_PER_CHANNEL_FULL * (MAX_BRIGHTNESS / 255.0)
    if estimate_ma <= CURRENT_BUDGET_MA:
        return pixels
    k = CURRENT_BUDGET_MA / estimate_ma
    return [(int(r * k), int(g * k), int(b * k)) for r, g, b in pixels]


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

            pixels = limit_current(render_frame(mode, now))
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
