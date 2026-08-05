#!/bin/bash
# Run on the Pi when wlan0 is unmanaged or SSH/home Wi-Fi is broken.
# Usage: bash pi/recover-network.sh

set -e

echo "=== Stopping fake AP (keeps wlan0 free) ==="
sudo systemctl disable fake-wifi-ap.service 2>/dev/null || true
sudo systemctl stop fake-wifi-ap.service 2>/dev/null || true
sudo systemctl stop hostapd dnsmasq 2>/dev/null || true
sudo iw dev uap0 del 2>/dev/null || true
sudo rm -f /run/fake-wifi/ap-phy /run/fake-wifi/ap-boot-delay /run/fake-wifi/home-conn 2>/dev/null || true

echo "=== Fixing NetworkManager (wlan1 unmanaged only) ==="
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/99-fake-wifi-usb-unmanaged.conf > /dev/null <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF

echo "=== Restoring wlan0 management ==="
sudo rfkill unblock wifi
sudo ip link set wlan0 up
sudo nmcli dev set wlan0 managed yes 2>/dev/null || true
sudo systemctl reload NetworkManager 2>/dev/null || sudo systemctl restart NetworkManager
sleep 3
sudo nmcli dev set wlan0 managed yes 2>/dev/null || true
sudo ip link set wlan0 up
sudo nmcli device connect wlan0 2>/dev/null || true

echo ""
echo "=== Status ==="
nmcli dev status 2>/dev/null || true
ip -br link | grep -E 'wlan|uap' || true

echo ""
echo "If wlan0 is still disconnected, connect manually:"
echo '  sudo nmcli dev wifi connect "YOUR_SSID" password '\''YOUR_PASSWORD'\'''
echo ""
echo "When home Wi-Fi works, test AP: sudo start-ap.sh"
echo "  (no USB → onboard AP-only; home Wi-Fi drops until sudo stop-ap.sh)"
