#!/bin/bash
# Run this once on your Pi to set everything up

# Then `sudo start-ap.sh` to start the AP
# Then `sudo stop-ap.sh` to stop the AP
# On the AP, to connect, do `ssh j@192.168.4.1`

# Get the actual user (not root if running with sudo)
REAL_USER=${SUDO_USER:-$USER}
if [ "$REAL_USER" = "root" ] || [ -z "$REAL_USER" ]; then
    REAL_USER=$(who am i | awk '{print $1}' 2>/dev/null || echo "pi")
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Stop AP during setup so wlan0 stays manageable (safe to re-run setup)
sudo systemctl disable fake-wifi-ap.service 2>/dev/null || true
sudo systemctl stop fake-wifi-ap.service 2>/dev/null || true
if [ -x /usr/local/bin/stop-ap.sh ]; then
    sudo /usr/local/bin/stop-ap.sh 2>/dev/null || true
fi

# Install packages (AP stack only — LED lib installed separately; see install_rpi_ws281x)
sudo apt update
sudo apt install -y hostapd dnsmasq lighttpd python3 iptables

# NeoPixel library: apt on Bookworm/Pi OS; pip on trixie where python3-rpi-ws281x is absent
install_rpi_ws281x() {
    # Verify as root — the LED systemd service runs as root, so root's
    # site-packages is what matters. A user-level pip install (~/.local)
    # would import fine for you but fail under systemd.
    if sudo python3 -c 'from rpi_ws281x import PixelStrip' 2>/dev/null; then
        echo "rpi_ws281x: already installed for root."
        return 0
    fi
    if apt-cache show python3-rpi-ws281x &>/dev/null; then
        echo "Installing python3-rpi-ws281x from apt..."
        if sudo apt install -y python3-rpi-ws281x &&
           sudo python3 -c 'from rpi_ws281x import PixelStrip' 2>/dev/null; then
            return 0
        fi
        echo "apt install python3-rpi-ws281x failed; trying pip..."
    else
        echo "python3-rpi-ws281x not in apt (common on Debian trixie) — installing via pip..."
    fi
    sudo apt install -y python3-dev python3-pip build-essential
    # Must be sudo pip so it installs into root's site-packages, not ~/.local
    if sudo pip3 install --break-system-packages rpi-ws281x 2>/dev/null ||
       sudo pip3 install rpi-ws281x 2>/dev/null; then
        if sudo python3 -c 'from rpi_ws281x import PixelStrip' 2>/dev/null; then
            return 0
        fi
    fi
    echo "WARNING: could not install rpi_ws281x for root — status LED service will not be enabled."
    return 1
}

FAKE_WIFI_HAS_WS281X=false
install_rpi_ws281x && FAKE_WIFI_HAS_WS281X=true

echo ""
echo "=== Network status (before AP config) ==="
if command -v nmcli >/dev/null 2>&1; then
    nmcli dev status 2>/dev/null || true
else
    echo "nmcli not available yet."
fi

# AP physical interface config (not overwritten if you already edited it)
sudo mkdir -p /etc/fake-wifi
if [ -f "$SCRIPT_DIR/pi/ap.conf" ]; then
    sudo cp -n "$SCRIPT_DIR/pi/ap.conf" /etc/fake-wifi/ap.conf
else
    echo "Warning: $SCRIPT_DIR/pi/ap.conf missing; using minimal /etc/fake-wifi/ap.conf"
    sudo tee /etc/fake-wifi/ap.conf > /dev/null <<'DEFAULT_AP_CONF'
AP_PHYS=auto
AP_PHYS_PREFER=usb
AP_PHYS_WAIT_SECS=15
DEFAULT_AP_CONF
fi

# Copy your files
sudo rm -rf /var/www/html/*
if [ -d "/home/$REAL_USER/fake-wifi-repo" ]; then
    sudo cp -r /home/$REAL_USER/fake-wifi-repo/* /var/www/html/
else
    echo "Warning: /home/$REAL_USER/fake-wifi-repo not found, trying current directory..."
    sudo cp -r "$(pwd)"/* /var/www/html/ 2>/dev/null || {
        echo "Error: Could not find fake-wifi-repo directory"
        exit 1
    }
fi

# Set up captive portal OS probe files (exact bodies where required)
CAPTIVE_DIR="$SCRIPT_DIR/captive-portal-files"
if [ -f "$CAPTIVE_DIR/hotspot-detect.html" ]; then
    sudo cp "$CAPTIVE_DIR/hotspot-detect.html" /var/www/html/hotspot-detect.html
else
    sudo sh -c 'echo "<!DOCTYPE html><html><head><meta http-equiv=\"refresh\" content=\"0; url=/\"><title>Success</title></head><body><script>window.location.href=\"/\";</script></body></html>" > /var/www/html/hotspot-detect.html'
fi
if [ -f "$CAPTIVE_DIR/ncsi.txt" ]; then
    sudo cp "$CAPTIVE_DIR/ncsi.txt" /var/www/html/ncsi.txt
else
    printf '%s' 'Microsoft NCSI' | sudo tee /var/www/html/ncsi.txt > /dev/null
fi
if [ -f "$CAPTIVE_DIR/connecttest.txt" ]; then
    sudo cp "$CAPTIVE_DIR/connecttest.txt" /var/www/html/connecttest.txt
else
    printf '%s' 'Microsoft Connect Test' | sudo tee /var/www/html/connecttest.txt > /dev/null
fi
if [ -f "$CAPTIVE_DIR/captive-portal-api.json" ]; then
    sudo cp "$CAPTIVE_DIR/captive-portal-api.json" /var/www/html/captive-portal-api.json
else
    sudo tee /var/www/html/captive-portal-api.json > /dev/null <<'CAPTIVE_JSON'
{"captive":true,"user-portal-url":"http://192.168.4.1/"}
CAPTIVE_JSON
fi
# /generate_204 and /gen_204 are handled by lighttpd 302 redirects (not static files)
sudo rm -f /var/www/html/generate_204 /var/www/html/gen_204

# Fix permissions for web server
sudo chown -R www-data:www-data /var/www/html/
sudo chmod -R 755 /var/www/html/
sudo find /var/www/html -type f -exec chmod 644 {} \;

# Configure hostapd (but don't enable auto-start)
# Using uap0 virtual interface so wlan0 can stay connected for SSH
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=uap0
driver=nl80211
ssid=BURNERNET
country_code=US
hw_mode=g
channel=7
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
EOF

# Tell hostapd where to find its config file
sudo sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || \
sudo sh -c 'echo "DAEMON_CONF=\"/etc/hostapd/hostapd.conf\"" >> /etc/default/hostapd'

# Configure dnsmasq
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.backup
sudo tee /etc/dnsmasq.conf > /dev/null <<EOF
interface=uap0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
# RFC 8908 captive portal URL via DHCP option 114 (Android 11+, iOS 14+)
# Lets the OS fetch the portal API immediately, bypassing DNS-probe games / Private DNS.
dhcp-option=114,"http://192.168.4.1/captive-portal-api.json"
address=/#/192.168.4.1
address=/burner-net.com/192.168.4.1
# Captive portal detection (explicit; wildcard above catches the rest)
address=/captive.apple.com/192.168.4.1
address=/connectivitycheck.gstatic.com/192.168.4.1
address=/connectivitycheck.android.com/192.168.4.1
address=/clients3.google.com/192.168.4.1
address=/clients4.google.com/192.168.4.1
address=/www.google.com/192.168.4.1
address=/play.googleapis.com/192.168.4.1
address=/android.clients.google.com/192.168.4.1
address=/www.msftconnecttest.com/192.168.4.1
address=/nmcheck.gnome.org/192.168.4.1
address=/network-test.debian.org/192.168.4.1
address=/detectportal.firefox.com/192.168.4.1
EOF

# Create start/stop scripts
sudo tee /usr/local/bin/start-ap.sh > /dev/null <<'SCRIPT'
#!/bin/bash
set -e

LOG_FILE="/var/log/ap-start.log"
mkdir -p /var/log

# shellcheck source=/dev/null
[ -f /etc/fake-wifi/ap.conf ] && . /etc/fake-wifi/ap.conf

list_wlans() {
    local i
    for i in $(ls /sys/class/net 2>/dev/null | grep -E '^wlan[0-9]+$' | sort -V); do
        echo "$i"
    done
}

is_usb_wlan() {
    local iface=$1 subs
    [ -e "/sys/class/net/$iface" ] || return 1
    subs=$(readlink -f "/sys/class/net/$iface/device/subsystem" 2>/dev/null) || return 1
    [[ "$subs" == *usb* ]] && return 0
    return 1
}

find_usb_wlan() {
    local w
    for w in $(list_wlans); do
        is_usb_wlan "$w" && { echo "$w"; return 0; }
    done
    return 1
}

wait_for_usb_wlan() {
    local w secs=${AP_PHYS_WAIT_SECS:-15} elapsed=0
    if [ "$secs" -le 0 ] 2>/dev/null; then
        find_usb_wlan
        return $?
    fi
    while [ "$elapsed" -lt "$secs" ]; do
        w=$(find_usb_wlan) && { echo "$w"; return 0; }
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

resolve_ap_phys() {
    local w
    if [ -n "${AP_PHYS:-}" ] && [ "$AP_PHYS" != "auto" ]; then
        if [ -e "/sys/class/net/$AP_PHYS" ]; then
            echo "$AP_PHYS"
            return 0
        fi
        if is_usb_wlan "$AP_PHYS" 2>/dev/null || [ "$AP_PHYS" = "wlan1" ]; then
            echo "ERROR: AP_PHYS=$AP_PHYS (USB radio) not found — check dongle and aic8800 driver" >&2
        else
            echo "ERROR: AP_PHYS=$AP_PHYS but /sys/class/net/$AP_PHYS not found" >&2
        fi
        return 1
    fi
    case "${AP_PHYS_PREFER:-usb}" in
        usb)
            w=$(wait_for_usb_wlan) && { echo "$w"; return 0; }
            echo "No USB wlan after ${AP_PHYS_WAIT_SECS:-15}s wait; falling back to onboard radio" >&2
            for w in $(list_wlans); do
                if ! is_usb_wlan "$w"; then echo "$w"; return 0; fi
            done
            ;;
        builtin)
            for w in $(list_wlans); do
                if ! is_usb_wlan "$w"; then echo "$w"; return 0; fi
            done
            ;;
    esac
    w=$(list_wlans | head -n1)
    if [ -n "$w" ]; then
        echo "$w"
        return 0
    fi
    echo "ERROR: No wlan interface found to attach uap0" >&2
    return 1
}

{
    echo "=========================================="
    echo "AP Start Log - $(date)"
    echo "=========================================="
    
    PHY=$(resolve_ap_phys) || exit 1
    sudo mkdir -p /run/fake-wifi
    echo "$PHY" | sudo tee /run/fake-wifi/ap-phy > /dev/null
    echo "Using physical Wi-Fi: $PHY (from /etc/fake-wifi/ap.conf)"
    if is_usb_wlan "$PHY"; then
        echo "Mode: dual-radio — AP on USB $PHY (external antenna); wlan0 free for home Wi-Fi / SSH"
    else
        echo "Mode: single-radio — AP on $PHY (STA+AP on same chip; USB dongle absent or wait timed out)"
    fi

    echo "Creating virtual AP interface uap0..."
    # Remove uap0 if it exists
    sudo iw dev uap0 del 2>/dev/null || true
    # Create uap0 as virtual AP interface from the chosen phy (often wlan0; USB dongle if present)
    sudo iw dev "$PHY" interface add uap0 type __ap
    
    echo "Unblocking WiFi (rfkill)..."
    sudo rfkill unblock wlan 2>/dev/null || true
    
    echo "Bringing uap0 up..."
    sudo ip link set uap0 up
    
    echo "Setting IP address on uap0..."
    sudo ip addr add 192.168.4.1/24 dev uap0 2>/dev/null || sudo ip addr replace 192.168.4.1/24 dev uap0
    
    echo "Unmasking hostapd (if needed)..."
    sudo systemctl unmask hostapd 2>/dev/null || true
    
    echo "Starting hostapd..."
    if sudo systemctl start hostapd; then
        sleep 2
        if sudo systemctl is-active --quiet hostapd; then
            echo "✓ hostapd is running"
        else
            echo "✗ hostapd failed to start. Recent logs:"
            sudo journalctl -u hostapd -n 20 --no-pager
            exit 1
        fi
    else
        echo "✗ Failed to start hostapd"
        sudo journalctl -u hostapd -n 20 --no-pager
        exit 1
    fi
    
    echo "(Re)starting dnsmasq so it binds to uap0..."
    sudo systemctl restart dnsmasq

    # Kill DNS-over-TLS (port 853) from clients with a TCP reset so Android's
    # Private DNS = Automatic fails fast and falls back to system DNS (our dnsmasq).
    # Without this, port 853 just times out (we have no upstream) and the captive
    # portal probe never fires.
    if command -v iptables >/dev/null 2>&1; then
        echo "Adding iptables rule to reject DoT (port 853) on uap0..."
        sudo iptables -D INPUT -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
        sudo iptables -I INPUT -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset || true
        sudo iptables -D FORWARD -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
        sudo iptables -I FORWARD -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    elif command -v nft >/dev/null 2>&1; then
        echo "Adding nftables rule to reject DoT (port 853) on uap0..."
        sudo nft add table inet fakewifi 2>/dev/null || true
        sudo nft 'add chain inet fakewifi input { type filter hook input priority 0 ; }' 2>/dev/null || true
        sudo nft flush chain inet fakewifi input 2>/dev/null || true
        sudo nft add rule inet fakewifi input iifname "uap0" tcp dport 853 reject with tcp reset || true
    else
        echo "WARNING: neither iptables nor nft found — Private DNS (port 853) NOT blocked. Android captive portal may be unreliable."
    fi

    echo "Starting post board API..."
    sudo systemctl start burnernet-api.service 2>/dev/null || true
    
    echo "Ensuring SSH is accessible..."
    sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true
    
    echo "Checking firewall (ufw)..."
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow 22/tcp 2>/dev/null || true
        echo "  SSH port 22 allowed"
    fi
    
    echo ""
    echo "=========================================="
    echo "AP started! SSID: BURNERNET"
    echo ""
    if is_usb_wlan "$PHY"; then
        echo "uap0 on $PHY broadcasts BURNERNET (USB antenna)."
        echo "wlan0: home Wi-Fi / SSH via NetworkManager."
        echo "Or join BURNERNET and SSH to j@192.168.4.1"
    else
        echo "uap0 on $PHY broadcasts BURNERNET (onboard radio, STA+AP)."
        echo "SSH via home Wi-Fi on $PHY OR join BURNERNET and SSH to j@192.168.4.1"
    fi
    echo ""
    echo "To check status: sudo systemctl status hostapd"
    echo "To view logs: sudo journalctl -u hostapd -f"
    echo "To view this log: cat $LOG_FILE"
    echo "=========================================="
    echo "Log saved to: $LOG_FILE"
} | tee -a "$LOG_FILE"
SCRIPT

sudo tee /usr/local/bin/stop-ap.sh > /dev/null <<'SCRIPT'
#!/bin/bash
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
sudo systemctl stop burnernet-api.service 2>/dev/null || true
if command -v iptables >/dev/null 2>&1; then
    sudo iptables -D INPUT -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    sudo iptables -D FORWARD -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
fi
if command -v nft >/dev/null 2>&1; then
    sudo nft delete table inet fakewifi 2>/dev/null || true
fi
sudo ip addr del 192.168.4.1/24 dev uap0 2>/dev/null || true
sudo ip link set uap0 down 2>/dev/null || true
sudo iw dev uap0 del 2>/dev/null || true
sudo rm -f /run/fake-wifi/ap-phy 2>/dev/null || true
echo "AP stopped. Virtual interface uap0 removed."
echo "Physical wlan is unchanged (still up if NetworkManager/wpa kept it)."
SCRIPT

sudo chmod +x /usr/local/bin/start-ap.sh /usr/local/bin/stop-ap.sh

# Create a log viewer script
sudo tee /usr/local/bin/view-ap-log.sh > /dev/null <<'SCRIPT'
#!/bin/bash
LOG_FILE="/var/log/ap-start.log"
if [ -f "$LOG_FILE" ]; then
    echo "=== AP Start Log ==="
    cat "$LOG_FILE"
    echo ""
    echo "=== Recent hostapd system logs ==="
    sudo journalctl -u hostapd -n 30 --no-pager
else
    echo "No log file found at $LOG_FILE"
    echo "AP may not have been started yet."
fi
SCRIPT

sudo chmod +x /usr/local/bin/view-ap-log.sh

# Don't auto-start hostapd/dnsmasq on boot — start-ap.sh owns their lifecycle
# (apt installs both as enabled by default; disable so they don't bind before uap0 exists)
sudo systemctl unmask hostapd 2>/dev/null || true
sudo systemctl disable hostapd
sudo systemctl disable dnsmasq
sudo systemctl stop dnsmasq 2>/dev/null || true
sudo systemctl stop hostapd 2>/dev/null || true

# Configure lighttpd to redirect all requests to portal
# Backup original config
sudo cp /etc/lighttpd/lighttpd.conf /etc/lighttpd/lighttpd.conf.backup 2>/dev/null || true

# Captive portal: drop-in conf (always refreshed) + remove legacy inline block
# Strip legacy inline captive rules (including fragments left by partial sed deletes)
if grep -qE 'generate_204|Captive portal configuration|url\.redirect-code' /etc/lighttpd/lighttpd.conf; then
    sudo awk '
        /^# Captive portal configuration/ { skip=1; next }
        skip && /^# Proxy \/api\// { skip=0 }
        skip && /^server\.modules \+= \( "mod_proxy" \)/ { skip=0 }
        skip { next }
        /url\.redirect-code/ { skip=1; next }
        skip && /^}$/ { skip=0; next }
        /url\.rewrite-once/ && /index\.html/ { skip=1; next }
        skip && /^}$/ { skip=0; next }
        { print }
    ' /etc/lighttpd/lighttpd.conf | sudo tee /etc/lighttpd/lighttpd.conf.tmp > /dev/null
    sudo mv /etc/lighttpd/lighttpd.conf.tmp /etc/lighttpd/lighttpd.conf
fi
sudo tee /etc/lighttpd/conf-available/fake-wifi-captive.conf > /dev/null <<'LIGHTTPD_CAPTIVE'
# Captive portal configuration (fake-wifi)
server.modules += ( "mod_redirect", "mod_rewrite", "mod_setenv" )

# OS captive probes — one url.redirect block (lighttpd rejects duplicate url.redirect keys)
$HTTP["url"] =~ "^/(generate_204|gen_204|hotspot-detect\.html|library/test/success\.html)$" {
    url.redirect = (
        "^/(generate_204|gen_204|hotspot-detect\.html|library/test/success\.html)$" => "http://192.168.4.1/"
    )
    url.redirect-code = 302
}

# RFC 8908 captive portal API (Android 11+, iOS 14+)
$HTTP["url"] == "/captive-portal-api.json" {
    setenv.set-response-header = ( "Content-Type" => "application/captive+json" )
}

# RFC 8908 well-known path — some clients fetch here directly
$HTTP["url"] =~ "^/\.well-known/captive-portal$" {
    url.rewrite-once = ( "^/.*" => "/captive-portal-api.json" )
    setenv.set-response-header = ( "Content-Type" => "application/captive+json" )
}

# Serve portal for any other hostname/path (google.com, etc.)
# Probe paths above must be excluded or rewrite wins and returns 200 + index.html
$HTTP["url"] !~ "^/(\.well-known/captive-portal|index\.html|generate_204|gen_204|hotspot-detect\.html|library/test/success\.html|ncsi\.txt|connecttest\.txt|captive-portal-api\.json|.*\.(html|css|js|jpg|jpeg|png|gif|ico|json|txt|pdf|svg|woff|woff2|ttf|eot|mp4|webm|map))" {
    url.rewrite-once = (
        "^/(.*)" => "/index.html"
    )
}
LIGHTTPD_CAPTIVE
sudo ln -sf ../conf-available/fake-wifi-captive.conf /etc/lighttpd/conf-enabled/90-fake-wifi-captive.conf
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf

# Add proxy pass for the post board API
if ! grep -q "mod_proxy" /etc/lighttpd/lighttpd.conf; then
    sudo tee -a /etc/lighttpd/lighttpd.conf > /dev/null <<'LIGHTTPD_PROXY'

# Proxy /api/* to the Python post board API on port 3000
server.modules += ( "mod_proxy" )
$HTTP["url"] =~ "^/api/" {
    proxy.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 3000 ) ) )
}
LIGHTTPD_PROXY
fi

# Create data directory for the post board
sudo mkdir -p /var/lib/burnernet
sudo chown www-data:www-data /var/lib/burnernet

# Set up the post board API as a systemd service
sudo tee /etc/systemd/system/burnernet-api.service > /dev/null <<SERVICE
[Unit]
Description=BurnerNet Post Board API
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /var/www/html/api/server.py
Restart=always
RestartSec=3
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable burnernet-api.service
sudo systemctl start burnernet-api.service

# Enable lighttpd (web server always runs)
sudo systemctl enable lighttpd
sudo systemctl restart lighttpd

# Ensure SSH is enabled and accessible
sudo systemctl enable ssh 2>/dev/null || sudo systemctl enable sshd 2>/dev/null || true
sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true

# Allow SSH through firewall if ufw is installed
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 22/tcp 2>/dev/null || true
fi

# Create systemd service for auto-starting AP on boot
sudo tee /etc/systemd/system/fake-wifi-ap.service > /dev/null <<'SERVICE'
[Unit]
Description=Fake WiFi Access Point (BURNERNET)
After=network-online.target networking.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/start-ap.sh
ExecStop=/usr/local/bin/stop-ap.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# Status LEDs (GPIO18, up to 4 pixels)
if [ -f "$SCRIPT_DIR/pi/leds.py" ]; then
    sudo cp "$SCRIPT_DIR/pi/leds.py" /usr/local/bin/fake-wifi-leds.py
    sudo chmod +x /usr/local/bin/fake-wifi-leds.py
fi
if [ -f "$SCRIPT_DIR/pi/fake-wifi-leds.service" ]; then
    sudo cp "$SCRIPT_DIR/pi/fake-wifi-leds.service" /etc/systemd/system/fake-wifi-leds.service
    sudo systemctl daemon-reload
    if [ "$FAKE_WIFI_HAS_WS281X" = true ]; then
        sudo systemctl enable fake-wifi-leds.service
        sudo systemctl restart fake-wifi-leds.service
        echo "Status LEDs: fake-wifi-leds.service enabled."
    else
        sudo systemctl disable --now fake-wifi-leds.service 2>/dev/null || true
        echo "Status LEDs: skipped (re-run setup after: pip3 install --break-system-packages rpi-ws281x)."
    fi
fi

# Install AP service unit (not enabled here — verify wlan0 uplink first)
sudo systemctl daemon-reload

# Keep NetworkManager on wlan0; only wlan1 (USB AP radio) is unmanaged
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/99-fake-wifi-usb-unmanaged.conf > /dev/null <<'NM_CONF'
[keyfile]
unmanaged-devices=interface-name:wlan1
NM_CONF
echo ""
echo "NetworkManager: wrote 99-fake-wifi-usb-unmanaged.conf (wlan1 only)."
echo "  wlan0 stays managed for home Wi-Fi / SSH."
echo "  NM was NOT reloaded during setup (avoids dropping your SSH session)."
echo "  After reboot, or if wlan1 still shows as managed: sudo systemctl reload NetworkManager"

echo ""
echo "=== Network status (post-setup) ==="
if command -v nmcli >/dev/null 2>&1; then
    nmcli dev status 2>/dev/null || true
    if nmcli -t -f DEVICE,STATE dev 2>/dev/null | grep -q '^wlan0:unmanaged'; then
        echo ""
        echo "WARNING: wlan0 is unmanaged. Recovery:"
        echo "  sudo nmcli dev set wlan0 managed yes"
        echo "  sudo ip link set wlan0 up"
        echo "  sudo nmcli dev wifi connect YOUR_SSID password 'YOUR_PASSWORD'"
    fi
else
    echo "nmcli not available; skip device check."
fi
ip -br link 2>/dev/null | grep -E 'wlan|uap' || true

echo ""
echo "=========================================="
echo "Setup complete!"
echo ""
echo "Safe boot sequence:"
echo "  1. Confirm wlan0 is connected to home Wi-Fi (nmcli dev status)"
echo "  2. Test AP once: sudo start-ap.sh && view-ap-log.sh"
echo "  3. Enable AP on boot: sudo systemctl enable --now fake-wifi-ap.service"
echo ""
echo "To start/stop AP without enabling boot:"
echo "  sudo start-ap.sh"
echo "  sudo stop-ap.sh"
echo "  view-ap-log.sh"
echo ""
echo "Two modes (when AP runs):"
echo "  USB dongle present: wlan0 = home Wi-Fi / SSH, wlan1 = BURNERNET AP (uap0)"
echo "  No USB dongle:      wlan0 = STA+AP on one radio (fallback)"
echo ""
echo "Config: sudo nano /etc/fake-wifi/ap.conf"
echo "  AP_PHYS=auto, AP_PHYS_PREFER=usb, AP_PHYS_WAIT_SECS=15"
echo ""
echo "Logs: /var/log/ap-start.log"
echo ""
echo "Status LEDs: GPIO18, 4 pixels (wire 1 now, chain more later)"
echo "  Rainbow = BURNERNET healthy; LED0 red-red flash = backup radio"
echo "  Yellow pulse = services restarting; Red pulse = AP down"
echo "=========================================="