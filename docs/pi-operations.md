# Raspberry Pi operations (BURNER-NET.COM)

**Read this when:** the AP vanished after `setup-pi.sh`, captive portal returns wrong HTTP codes, or you are handing off to another LLM mid-debug.

**Hardware (jw1):** Pi Zero 2 W + USB Tenda AIC8800 (`wlan1`). Onboard `wlan0` = home Wi‑Fi / SSH via NetworkManager. AP = virtual **`uap0`** on **`wlan1`**, SSID **`BURNER-NET.COM`** (open), portal **`http://192.168.4.1/`**.

---

## Standard deploy workflow (Mac → Pi)

Always in this order:

### 1. Rsync repo to Pi

From the Mac (quotes required — space in `Fake Wifi`):

```bash
rsync -avz \
  --exclude='.git' \
  --exclude='.DS_Store' \
  --exclude='z-archive' \
  "/Users/john/Documents/Projects/Fake Wifi/fake-wifi-repo/" \
  j@jw1.local:~/fake-wifi-repo/
```

Use `.` as source if already `cd` into the repo. Expect a **non-zero total size**; `speedup is 0.00` / status 23 means the source path was wrong.

### 2. Run setup on Pi (home Wi‑Fi first)

```bash
ssh j@jw1.local
cd ~/fake-wifi-repo && bash setup-pi.sh
```

**Setup intentionally:**
- Runs **`stop-ap.sh`** at the start → **BURNER-NET.COM disappears** until you start the AP again.
- Does **not** `enable` **`fake-wifi-ap.service`** (avoids bricking SSH during install).
- Writes captive rules to **`/etc/lighttpd/conf-available/fake-wifi-captive.conf`** (enabled via `conf-enabled/90-fake-wifi-captive.conf`).
- Removes legacy inline captive blocks from **`/etc/lighttpd/lighttpd.conf`** when present.

### 3. Start the AP (required after every setup)

```bash
sudo start-ap.sh
```

Or: `sudo systemctl start fake-wifi-ap.service` (same script).

### 4. Verify before telling guests to connect

On the Pi:

```bash
ip -br a show uap0                    # UP, 192.168.4.1/24
systemctl is-active hostapd dnsmasq   # both active
sudo iw dev uap0 info | grep ssid     # BURNER-NET.COM

curl -sI http://127.0.0.1/generate_204 | head -5
# MUST be: HTTP/1.1 302 Found
#          Location: http://192.168.4.1/

getent hosts burner-net.com    # 192.168.4.1
curl -sI -H "Host: burner-net.com" http://127.0.0.1/ | head -3   # 200, portal HTML
```

**If phones don’t see BURNER-NET.COM:** AP is almost certainly stopped — run step 3, don’t re-run setup unless you need config changes.

### 5. Enable AP on boot (optional, after dual-radio is stable)

```bash
sudo systemctl enable --now fake-wifi-ap.service
```

---

## Boot-time safety: `AP_BOOT_DELAY_SECS`

When `fake-wifi-ap.service` is enabled, `start-ap.sh` **sleeps for `AP_BOOT_DELAY_SECS` (default 30s) at boot only** before touching any interface. This is your SSH recovery window.

**Why it exists:** without a USB dongle, `start-ap.sh` runs **onboard AP-only** (releases NetworkManager on `wlan0`, home Wi‑Fi drops until `stop-ap.sh`). The delay gives you time to SSH in and abort before that happens. With USB present, home Wi‑Fi stays up.

**Configuration** in `/etc/fake-wifi/ap.conf`:

```
AP_BOOT_DELAY_SECS=30   # seconds; 0 disables; only applies at boot
```

**Important properties:**

- Only triggers when **systemd** starts the service (detected via `$INVOCATION_ID`).
- Manual `sudo start-ap.sh` runs are **instant** — no delay.
- Logged to `/var/log/ap-start.log` as the first line at boot.

### Abort during the 30s window

If you SSH in during boot and see BURNER-NET.COM isn't there yet but you want to keep home Wi‑Fi (e.g. no USB today and you need `jw1.local`):

```bash
sudo systemctl stop fake-wifi-ap          # cancels the pending boot start
sudo systemctl disable fake-wifi-ap       # keep it disabled across reboots
```

Then debug the dongle / driver without time pressure. Re-enable later:

```bash
sudo systemctl enable --now fake-wifi-ap
```

### Tune or remove the delay

Edit `/etc/fake-wifi/ap.conf`:

```bash
sudo nano /etc/fake-wifi/ap.conf
# AP_BOOT_DELAY_SECS=0    # boot the AP immediately (no recovery window)
# AP_BOOT_DELAY_SECS=120  # extra cautious
```

No service restart needed; the value is read on each `start-ap.sh` invocation.

---

## Captive portal / lighttpd pitfalls

| `curl -sI http://127.0.0.1/generate_204` | Meaning | Fix |
|------------------------------------------|---------|-----|
| **200** + `Content-Type: text/html` | Catch-all rewrite served `index.html` | Ensure drop-in exists; probe paths excluded from rewrite; no static `/var/www/html/generate_204` |
| **404** | Redirect rules not loaded (config parse error) | `sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf` — fix errors, restart |
| **302** + `Location: http://192.168.4.1/`` | Correct for Android auto-open | — |

**Do not** partially delete captive blocks with:

```bash
sudo sed -i '/# Captive portal configuration/,/^}$/d' /etc/lighttpd/lighttpd.conf
```

That leaves **orphaned** `$HTTP[...]` fragments and breaks `lighttpd -tt`. Re-run **`setup-pi.sh`** or restore from `/etc/lighttpd/lighttpd.conf.backup`.

**lighttpd quirk:** only **one** `url.redirect` block per file scope — multiple `$HTTP` blocks each setting `url.redirect` cause *Duplicate config variable* and redirects won’t load.

**Stale static files:** remove `/var/www/html/generate_204` and `gen_204` if present (setup does this).

---

## SSH access

| Network | Command |
|---------|---------|
| Home Wi‑Fi | `ssh j@jw1.local` |
| BURNER-NET.COM only | `ssh j@192.168.4.1` (may need `ssh-keygen -R 192.168.4.1` after reflash) |

Recovery if `wlan0` is broken: `bash ~/fake-wifi-repo/pi/recover-network.sh`

---

## Status LEDs (GPIO18 NeoPixel)

`pi/leds.py` → `fake-wifi-leds.service`, fully independent of the AP stack (own systemd unit, just polls AP state every 0.5s). Safe to stop/start without affecting BURNER-NET.

| Mode | Pattern |
|------|---------|
| Boot delay | Flashing red |
| Off-air (AP not broadcasting) | Solid red |
| Onboard AP up | Green bounce (4s) → rainbow glow (4s), repeat |
| USB AP up | White bounce (4s) → rainbow glow (4s), repeat |

**Two known hardware gotchas — both bit us once, both are one-time fixes per Pi:**

1. **Onboard audio conflicts with GPIO18 PWM.** Even on boards with no headphone jack (Pi Zero 2 W), `dtparam=audio=on` loads `snd_bcm2835`, which shares the same PWM peripheral as GPIO18. Left on, you'll see random single-pixel glitches to garbage/rainbow colors, usually most visible around Wi‑Fi radio state changes. `setup-pi.sh` disables this automatically (`dtparam=audio=off` in `/boot/firmware/config.txt`) when the LED lib installs — **takes a reboot to apply**. If you ever see stray flicker on a pixel, check this first: `grep dtparam=audio /boot/firmware/config.txt`.
2. **Strip color order varies by NeoPixel batch.** `rpi_ws281x` defaults to `GRB` wire order; some strips are wired `RGB` (sending red shows green and vice versa). `pi/leds.py` hardcodes `WS2811_STRIP_RGB` for this build's strip (confirmed via `pi/led-color-test.py`). If you swap in a different strip and colors look swapped, run `sudo python3 pi/led-color-test.py` (stop the service first) to see the actual order, then override with `FAKE_WIFI_LED_STRIP_TYPE=GRB` (or whichever matches) as an `Environment=` line in `/etc/systemd/system/fake-wifi-leds.service`.

---

## Android auto-popup (what we optimize for)

Android is **much pickier than iPhone**. Goal: **“Sign in to network”** notification or browser sheet without guests typing URLs.

**How Android decides (simplified):**

1. **Android 11+:** DHCP option **captive-portal** → fetch `http://192.168.4.1/.well-known/captive-portal` → if `captive: true`, prompt with `user-portal-url`.
2. **Fallback:** HTTP/HTTPS probes to `www.google.com/generate_204`, etc. → expect **204** on real internet; on a portal, **302** to login.

**Why it often failed before:** probes use **HTTPS** first; the Pi had no **:443**, so the check died before any redirect. `setup-pi.sh` now adds self-signed HTTPS + fixes DHCP option path.

**Still breaks on some phones if:**

- **Private DNS** is On (Strict/Automatic) — uses Cloudflare/Google DNS, not the Pi. **One sign at check-in: turn it Off.**
- OEM skin hides the notification (check shade for “Sign in to network”).
- Mobile data + Wi‑Fi conflict — briefly disable mobile data when testing.

**Verify on the Pi (AP running):**

```bash
curl -sI http://127.0.0.1/generate_204 | head -3          # 302 → portal
curl -skI https://127.0.0.1/generate_204 | head -3       # 302 (self-signed TLS)
curl -s http://127.0.0.1/.well-known/captive-portal      # captive JSON
```

After changing `setup-pi.sh`: rsync → `bash setup-pi.sh` → `sudo start-ap.sh` → test with a real Android on Private DNS **Off**.

## Android instructions (copy to guests — fallback only)

1. Join **`BURNER-NET.COM`** (no password).
2. Look for **Sign in to network** (notification or popup) and tap it.
3. If nothing: **Private DNS → Off**, forget network, rejoin.
4. Last resort: open **`http://192.168.4.1/`** in the browser address bar.

---

## Key files

| File | Role |
|------|------|
| `setup-pi.sh` | Installer: packages, `/var/www/html`, hostapd, dnsmasq, lighttpd captive drop-in, `start-ap.sh` |
| `pi/ap.conf` → `/etc/fake-wifi/ap.conf` | `AP_PHYS=auto`, USB preferred, `AP_BOOT_DELAY_SECS` |
| `pi/start-ap.sh` → `/usr/local/bin/start-ap.sh` | Creates `uap0`, starts hostapd + dnsmasq; onboard = AP-only |
| `pi/stop-ap.sh` → `/usr/local/bin/stop-ap.sh` | Tears down AP; restores saved home Wi‑Fi after onboard mode |
| `pi/recover-network.sh` | NM recovery for `wlan0` |
| `captive-portal-files/` | `ncsi.txt`, `connecttest.txt`, `captive-portal-api.json`, etc. |

---

## LLM handoff checklist

When continuing work on this repo:

1. Confirm **AP is running** (`uap0`, hostapd) — not just lighttpd.
2. After any **`setup-pi.sh`** run, tell the user to **`sudo start-ap.sh`** unless you started it yourself.
3. Verify **`generate_204` → 302** before debugging phone UX.
4. Rsync **before** setup if `setup-pi.sh` changed on Mac.
5. Don’t enable broad NetworkManager `unmanaged-devices` rules (bricked `wlan0` historically — setup only unmanagers `wlan1`).
6. Guest Android issues → **Private DNS** first, then manual portal URL.
7. **`AP_BOOT_DELAY_SECS`** in `/etc/fake-wifi/ap.conf` is the SSH recovery window — only fires under systemd, not on manual `start-ap.sh`. If a user reports "AP took a minute to come up after reboot" that's expected. Without USB, onboard AP-only drops home Wi‑Fi until `stop-ap.sh`.
