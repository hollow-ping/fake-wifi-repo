# Raspberry Pi operations (BURNERNET)

**Read this when:** the AP vanished after `setup-pi.sh`, captive portal returns wrong HTTP codes, or you are handing off to another LLM mid-debug.

**Hardware (jw1):** Pi Zero 2 W + USB Tenda AIC8800 (`wlan1`). Onboard `wlan0` = home Wi‑Fi / SSH via NetworkManager. AP = virtual **`uap0`** on **`wlan1`**, SSID **`BURNERNET`** (open), portal **`http://192.168.4.1/`**.

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
- Runs **`stop-ap.sh`** at the start → **BURNERNET disappears** until you start the AP again.
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
sudo iw dev uap0 info | grep ssid     # BURNERNET

curl -sI http://127.0.0.1/generate_204 | head -5
# MUST be: HTTP/1.1 302 Found
#          Location: http://192.168.4.1/
```

**If phones don’t see BURNERNET:** AP is almost certainly stopped — run step 3, don’t re-run setup unless you need config changes.

### 5. Enable AP on boot (optional, after dual-radio is stable)

```bash
sudo systemctl enable --now fake-wifi-ap.service
```

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
| BURNERNET only | `ssh j@192.168.4.1` (may need `ssh-keygen -R 192.168.4.1` after reflash) |

Recovery if `wlan0` is broken: `bash ~/fake-wifi-repo/pi/recover-network.sh`

---

## Android instructions (copy to guests)

1. Join Wi‑Fi **`BURNERNET`** (no password).
2. Tap **Sign in to network** when it appears.
3. If nothing appears:
   - **Settings → Network → Private DNS → Off** (Automatic/Strict breaks captive detection).
   - Forget **BURNERNET**, rejoin.
   - Open **`http://192.168.4.1/`** manually (http, not https).
4. Optional: turn off mobile data / VPN briefly.
5. Follow the portal (demo only — no real accounts on the Pi).

---

## Key files

| File | Role |
|------|------|
| `setup-pi.sh` | Installer: packages, `/var/www/html`, hostapd, dnsmasq, lighttpd captive drop-in, `start-ap.sh` |
| `pi/ap.conf` → `/etc/fake-wifi/ap.conf` | `AP_PHYS=auto`, USB preferred |
| `/usr/local/bin/start-ap.sh` | Creates `uap0`, starts hostapd + dnsmasq |
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
