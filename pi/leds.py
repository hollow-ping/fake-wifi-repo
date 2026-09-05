#!/usr/bin/env python3
"""
Status LEDs for Fake WiFi (GPIO18, 4 NeoPixels via rpi_ws281x PWM).

The Pi Zero is bad at WS2812 timing: GPIO18 is PWM0, which fights Wi‑Fi DMA
and leftover analog-audio PWM. Bit slips latch as random colors. We cannot
fully fix that in software. This file just makes glitches rarer and less
obvious:

- All 4 pixels always the same color (no bounce / rainbow chase).
- show() at most a few times per second, twice per update to overwrite slips.
- Boot-delay flag is ignored unless fake-wifi-ap is actually activating
  (a leftover /run/fake-wifi/ap-boot-delay used to flash forever).

On-air pixels 1..N flicker random colors (rest off). N is the max of
anyone on the AP: 2 = broadcasting empty, 3 = associated / intranet,
4 = at least one guest on a connect-flow page.

Off-air still uses the slow status blinks. Connecting is per-guest in
/var/lib/burnernet/led-portal.json.
"""

from __future__ import annotations

import json
import os
import random
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
# GPIO18 = PWM channel 0. DMA 10 is the rpi_ws281x default; 5 sometimes
# collides with SD card on older Pis, 10 collides with SPI (we don't use SPI).
LED_FREQ_HZ = 800000
LED_DMA = int(os.environ.get("FAKE_WIFI_LED_DMA", "10"))
LED_CHANNEL = 0

# Keep protocol brightness modest so the 5V burst during show() sags less.
MAX_BRIGHTNESS = int(os.environ.get("FAKE_WIFI_LED_BRIGHTNESS", "64"))
HALF = 128
CONNECTED_GREEN_LEVEL = int(os.environ.get("FAKE_WIFI_LED_CONNECTED_GREEN", "48"))

MA_PER_CHANNEL_FULL = 20.0
CURRENT_BUDGET_MA = float(os.environ.get("FAKE_WIFI_LED_BUDGET_MA", "50"))

_STRIP_TYPE_NAME = os.environ.get("FAKE_WIFI_LED_STRIP_TYPE", "RGB").strip().upper()
STRIP_TYPE = getattr(ws, f"WS2811_STRIP_{_STRIP_TYPE_NAME}", ws.WS2811_STRIP_RGB)

AP_PHY_FILE = "/run/fake-wifi/ap-phy"
AP_IFACE_FILE = "/run/fake-wifi/ap-iface"
BOOT_DELAY_FLAG = "/run/fake-wifi/ap-boot-delay"
STARTING_FLAG = "/run/fake-wifi/ap-starting"
LED_PORTAL_FILE = os.environ.get(
    "FAKE_WIFI_LED_PORTAL_FILE", "/var/lib/burnernet/led-portal.json"
)
PORTAL_CONNECTING_TTL_SEC = float(os.environ.get("FAKE_WIFI_LED_PORTAL_TTL", "8"))

AP_UNITS = ("fake-wifi-ap.service", "fake-wifi-ap-manual.service")
POLL_INTERVAL = 0.5
FRAME_INTERVAL = 0.12
RESYNC_INTERVAL = 8.0
SHOW_RESET_SEC = 0.0004

FLASH_PERIOD_SEC = 1.2
FLICKER_OFF_CHANCE = 0.4

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
    USB = auto()  # parked — see is_usb_phy / evaluate_mode
    CONNECTED = auto()
    CONNECTING = auto()


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
    """True only while systemd is actually in the AP boot-delay window.

    start-ap.sh leaves /run/fake-wifi/ap-boot-delay if killed mid-sleep;
    that used to freeze the strip in 'delay' forever.
    """
    if not os.path.isfile(BOOT_DELAY_FLAG):
        return False
    if any(service_active_state(unit) == "activating" for unit in AP_UNITS):
        return True
    try:
        os.unlink(BOOT_DELAY_FLAG)
    except OSError:
        pass
    return False


def read_ap_phy() -> str:
    try:
        with open(AP_PHY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_usb_phy(iface: str) -> bool:
    # USB dual-radio parked (Sep 2026 — no dongle). Restore evaluate_mode check.
    # if not iface or not os.path.isdir(f"/sys/class/net/{iface}"):
    #     return False
    # device = f"/sys/class/net/{iface}/device"
    # if not os.path.exists(device):
    #     return False
    # try:
    #     subsystem = os.path.realpath(os.path.join(device, "subsystem"))
    # except OSError:
    #     return False
    # return "usb" in subsystem
    return False


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


def _guest_connecting(entry: object, now: float) -> bool:
    if not isinstance(entry, dict) or entry.get("phase") != "connecting":
        return False
    try:
        ts = float(entry.get("ts", 0))
    except (TypeError, ValueError):
        return False
    return (now - ts) <= PORTAL_CONNECTING_TTL_SEC


def is_portal_connecting() -> bool:
    """True if ANY guest is on a connect-flow page (max of everyone)."""
    try:
        with open(LED_PORTAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    now = time.time()
    guests = data.get("guests")
    if isinstance(guests, dict) and guests:
        return any(_guest_connecting(g, now) for g in guests.values())
    return _guest_connecting(data, now)


def evaluate_mode() -> LedMode:
    if is_boot_delay():
        return LedMode.BOOT_DELAY
    if not is_broadcasting():
        return LedMode.STARTING if is_starting() else LedMode.OFF_AIR
    if is_portal_connecting():
        return LedMode.CONNECTING
    if has_client():
        return LedMode.CONNECTED
    # USB dual-radio parked — blue bounce on USB phy.
    # if is_usb_phy(read_ap_phy()):
    #     return LedMode.USB
    return LedMode.ONBOARD


def flash_on(t: float, period: float = FLASH_PERIOD_SEC) -> bool:
    return t % period < period / 2


def frame_solid(color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    return [color] * LED_COUNT


def frame_blink(t: float, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    return frame_solid(color if flash_on(t) else BLACK)


def frame_random_flicker(n_lit: int) -> list[tuple[int, int, int]]:
    """First n_lit pixels independently on/off with a random color; rest off."""
    n_lit = max(0, min(LED_COUNT, n_lit))
    out: list[tuple[int, int, int]] = []
    for i in range(LED_COUNT):
        if i >= n_lit or random.random() < FLICKER_OFF_CHANCE:
            out.append(BLACK)
        else:
            out.append(
                (random.randint(32, 255), random.randint(32, 255), random.randint(32, 255))
            )
    return out


def render_frame(mode: LedMode, t: float) -> list[tuple[int, int, int]]:
    if mode == LedMode.BOOT_DELAY:
        return frame_blink(t, RED_HALF)
    if mode == LedMode.STARTING:
        return frame_blink(t, GREEN_HALF)
    if mode == LedMode.OFF_AIR:
        return frame_solid(RED_FULL)
    if mode == LedMode.CONNECTING:
        return frame_random_flicker(4)
    if mode == LedMode.CONNECTED:
        return frame_random_flicker(3)
    # USB dual-radio parked. Broadcasting, nobody associated: first 2.
    # if mode == LedMode.USB:
    #     return frame_random_flicker(2)
    return frame_random_flicker(2)


def limit_current(pixels: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if CURRENT_BUDGET_MA <= 0:
        return pixels
    channels_lit = sum(sum(p) for p in pixels) / 255.0
    estimate_ma = channels_lit * MA_PER_CHANNEL_FULL * (MAX_BRIGHTNESS / 255.0)
    if estimate_ma <= CURRENT_BUDGET_MA:
        return pixels
    k = CURRENT_BUDGET_MA / estimate_ma
    return [(int(r * k), int(g * k), int(b * k)) for r, g, b in pixels]


def push_pixels(strip: PixelStrip, pixels: list[tuple[int, int, int]]) -> None:
    for i, (r, g, b) in enumerate(pixels):
        strip.setPixelColor(i, Color(r, g, b))
    strip.show()
    time.sleep(SHOW_RESET_SEC)
    strip.show()


def main() -> None:
    strip = PixelStrip(
        num=LED_COUNT,
        pin=LED_PIN,
        freq_hz=LED_FREQ_HZ,
        dma=LED_DMA,
        invert=False,
        brightness=MAX_BRIGHTNESS,
        channel=LED_CHANNEL,
        strip_type=STRIP_TYPE,
    )
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
                push_pixels(strip, pixels)
                last_pixels = pixels
                last_push = now
            time.sleep(FRAME_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        push_pixels(strip, frame_solid(BLACK))


if __name__ == "__main__":
    main()
