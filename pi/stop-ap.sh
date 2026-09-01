#!/bin/bash
# Tear down BURNER-NET.COM. Restores home Wi-Fi after single-radio (onboard) mode.
set -e

RUN_DIR=/run/fake-wifi
AP_ADDR=192.168.4.1

is_usb_wlan() {
    local iface=$1 subs
    [ -e "/sys/class/net/$iface" ] || return 1
    subs=$(readlink -f "/sys/class/net/$iface/device/subsystem" 2>/dev/null) || return 1
    [[ "$subs" == *usb* ]] && return 0
    return 1
}

PHY=$(cat "$RUN_DIR/ap-phy" 2>/dev/null || true)
AP_IFACE=$(cat "$RUN_DIR/ap-iface" 2>/dev/null || true)
HOME_CONN=$(cat "$RUN_DIR/home-conn" 2>/dev/null || true)

SINGLE_RADIO=0
if [ -n "$PHY" ] && ! is_usb_wlan "$PHY"; then
    SINGLE_RADIO=1
elif [ -n "$HOME_CONN" ]; then
    SINGLE_RADIO=1
    PHY=${PHY:-wlan0}
elif [ -z "$PHY" ]; then
    PHY=wlan0
fi
AP_IFACE=${AP_IFACE:-uap0}

# Stopping hostapd drops any SSH session riding on the AP itself, which would kill
# this script long before it restores home Wi-Fi — leaving the Pi with no network
# at all. Hand off to systemd so the teardown always runs to completion.
detach_if_needed() {
    if [ -n "${FAKE_WIFI_DETACHED:-}" ] || [ -n "${INVOCATION_ID:-}" ]; then
        return 0
    fi
    if [ -z "${SSH_CONNECTION:-}" ]; then
        return 0
    fi
    local server_ip
    server_ip=$(echo "$SSH_CONNECTION" | awk '{print $3}')
    if [ "$server_ip" != "$AP_ADDR" ]; then
        return 0
    fi
    echo "This SSH session runs over the AP — continuing teardown via systemd..."
    echo "  Home Wi-Fi comes back in a few seconds; reconnect with: ssh j@jw1.local"
    sudo systemd-run \
        --unit=fake-wifi-ap-stop \
        --collect \
        --property=Type=oneshot \
        --setenv=FAKE_WIFI_DETACHED=1 \
        /usr/local/bin/stop-ap.sh
    exit 0
}

detach_if_needed
trap '' HUP

# Stop AP daemons (may have been started via systemd or directly)
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true
sudo pkill -x hostapd 2>/dev/null || true
sudo pkill -x dnsmasq 2>/dev/null || true
sudo systemctl stop burnernet-api.service 2>/dev/null || true

if command -v iptables >/dev/null 2>&1; then
    sudo iptables -D INPUT -i "$AP_IFACE" -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    sudo iptables -D FORWARD -i "$AP_IFACE" -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    # Also clear classic uap0 rules if iface differed
    sudo iptables -D INPUT -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    sudo iptables -D FORWARD -i uap0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
fi
if command -v nft >/dev/null 2>&1; then
    sudo nft delete table inet fakewifi 2>/dev/null || true
fi

sudo ip addr del 192.168.4.1/24 dev "$AP_IFACE" 2>/dev/null || true
sudo ip addr del 192.168.4.1/24 dev uap0 2>/dev/null || true
sudo ip addr del 192.168.4.1/24 dev wlan0 2>/dev/null || true

sudo ip link set uap0 down 2>/dev/null || true
sudo iw dev uap0 del 2>/dev/null || true

sudo rm -f "$RUN_DIR/ap-phy" "$RUN_DIR/ap-boot-delay" "$RUN_DIR/ap-starting" \
    "$RUN_DIR/ap-iface" "$RUN_DIR/hostapd.conf" "$RUN_DIR/dnsmasq.conf" 2>/dev/null || true

echo "AP stopped."

if [ "$SINGLE_RADIO" -eq 1 ]; then
    echo "Single-radio: restoring NetworkManager on $PHY..."
    sudo nmcli device set "$PHY" managed yes 2>/dev/null || true
    sudo rfkill unblock wlan 2>/dev/null || true
    sudo ip link set "$PHY" up 2>/dev/null || true
    sleep 1
    if [ -n "$HOME_CONN" ]; then
        echo "  Bringing up saved connection: $HOME_CONN"
        if sudo nmcli connection up "$HOME_CONN" ifname "$PHY"; then
            echo "  ✓ Reconnected to $HOME_CONN"
        else
            echo "  WARNING: could not up '$HOME_CONN' — try: sudo nmcli device wifi connect ..."
        fi
    else
        echo "  No saved home connection; NM will auto-connect if a profile exists."
        sudo nmcli device connect "$PHY" 2>/dev/null || true
    fi
    sudo rm -f "$RUN_DIR/home-conn" 2>/dev/null || true
else
    echo "Dual-radio: home Wi-Fi should still be up."
    sudo rm -f "$RUN_DIR/home-conn" 2>/dev/null || true
fi
