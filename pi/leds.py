#!/usr/bin/env python3
"""
Status LEDs for Fake WiFi (GPIO18, up to 4 NeoPixels).

Priority: down (red pulse) > fixing (yellow pulse) > healthy (rainbow).
When healthy on fallback radio (not wlan1), LED 0 does a red-red flash every 3s.
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
POLL_INTERVAL = 0.5
FRAME_INTERVAL = 0.02

RAINBOW_CYCLE_SEC = 12.0
HUE_SPACING = 0.22  # hue offset between adjacent LEDs
PULSE_CYCLE_SEC = 2.5

BACKUP_FLASH_INTERVAL = 3.0
BACKUP_FLASH_ON_SEC = 0.12
BACKUP_FLASH_GAP_SEC = 0.08

TRANSITIONAL_STATES = frozenset(
    {"activating", "deactivating", "reloading", "refreshing"}
)


class HealthState(Enum):
    DOWN = auto()
    FIXING = auto()
    HEALTHY = auto()


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


def read_ap_phy() -> str:
    try:
        with open(AP_PHY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_backup_mode() -> bool:
    phy = read_ap_phy()
    return bool(phy) and phy != "wlan1"


def is_transitional() -> bool:
    for unit in ("hostapd", "dnsmasq"):
        if service_active_state(unit) in TRANSITIONAL_STATES:
            return True
    return False


def is_healthy() -> bool:
    if not uap0_exists():
        return False
    return (
        service_active_state("hostapd") == "active"
        and service_active_state("dnsmasq") == "active"
    )


def evaluate_health() -> HealthState:
    if is_transitional():
        return HealthState.FIXING
    if is_healthy():
        return HealthState.HEALTHY
    if not uap0_exists():
        return HealthState.DOWN
    hostapd = service_active_state("hostapd")
    dnsmasq = service_active_state("dnsmasq")
    if hostapd in TRANSITIONAL_STATES or dnsmasq in TRANSITIONAL_STATES:
        return HealthState.FIXING
    if hostapd == "active" and dnsmasq == "active":
        return HealthState.HEALTHY
    if hostapd in ("failed", "inactive") and dnsmasq in ("failed", "inactive"):
        return HealthState.DOWN
    return HealthState.FIXING


def pulse_brightness(t: float, cycle: float = PULSE_CYCLE_SEC) -> float:
    return 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / cycle))


def backup_flash_active(t: float) -> bool:
    phase = t % BACKUP_FLASH_INTERVAL
    first = phase < BACKUP_FLASH_ON_SEC
    second = (
        BACKUP_FLASH_ON_SEC
        <= phase
        < BACKUP_FLASH_ON_SEC + BACKUP_FLASH_GAP_SEC + BACKUP_FLASH_ON_SEC
    ) and phase >= BACKUP_FLASH_ON_SEC + BACKUP_FLASH_GAP_SEC
    return first or second


def frame_rainbow(t: float, backup: bool) -> list[tuple[int, int, int]]:
    base_hue = (t / RAINBOW_CYCLE_SEC) % 1.0
    pulse = pulse_brightness(t, RAINBOW_CYCLE_SEC / 2)
    pixels: list[tuple[int, int, int]] = []
    for i in range(LED_COUNT):
        if i == 0 and backup and backup_flash_active(t):
            pixels.append((255, 0, 0))
            continue
        hue = (base_hue + i * HUE_SPACING) % 1.0
        pixels.append(hsv_to_rgb(hue, 1.0, pulse))
    return pixels


def frame_pulse(t: float, hue: float) -> list[tuple[int, int, int]]:
    v = pulse_brightness(t)
    rgb = hsv_to_rgb(hue, 1.0, v)
    return [rgb] * LED_COUNT


def render_frame(state: HealthState, t: float) -> list[tuple[int, int, int]]:
    if state == HealthState.DOWN:
        return frame_pulse(t, 0.0)  # red
    if state == HealthState.FIXING:
        return frame_pulse(t, 0.14)  # yellow (~50deg)
    return frame_rainbow(t, backup=is_backup_mode())


def main() -> None:
    strip = PixelStrip(LED_COUNT, LED_PIN, brightness=MAX_BRIGHTNESS)
    strip.begin()

    health = HealthState.DOWN
    last_poll = 0.0

    try:
        while True:
            now = time.time()
            if now - last_poll >= POLL_INTERVAL:
                health = evaluate_health()
                last_poll = now

            pixels = render_frame(health, now)
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
