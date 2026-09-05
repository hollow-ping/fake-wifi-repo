#!/bin/bash
# Bring up BURNER-NET.COM.
# Always onboard AP-only for now (hostapd on wlan0; brcmfmac does not reliably
# AP on a virtual uap0). Home Wi-Fi drops until stop-ap.sh.
#
# USB dual-radio is parked (Sep 2026 — no dongle). Search this file for
# "USB dual-radio parked" to restore: uncomment wait_for_usb in resolve_ap_phys
# and the uap0 branch. Until then we never wait for / bind to a USB wlan.
set -eo pipefail

LOG_FILE="/var/log/ap-start.log"
RUN_DIR=/run/fake-wifi
HOSTAPD_RUN="$RUN_DIR/hostapd.conf"
DNSMASQ_RUN="$RUN_DIR/dnsmasq.conf"
STARTING_FLAG="$RUN_DIR/ap-starting"
mkdir -p /var/log

# shellcheck source=/dev/null
[ -f /etc/fake-wifi/ap.conf ] && . /etc/fake-wifi/ap.conf

# Boot-only delay under systemd (skipped for FAKE_WIFI_DETACHED re-execs).
if [ -z "${FAKE_WIFI_DETACHED:-}" ] && [ -n "${INVOCATION_ID:-}" ] && [ "${AP_BOOT_DELAY_SECS:-0}" -gt 0 ] 2>/dev/null; then
    echo "fake-wifi-ap: boot delay ${AP_BOOT_DELAY_SECS}s (SSH on wlan0 to abort: sudo systemctl stop fake-wifi-ap)" | tee -a "$LOG_FILE"
    sudo mkdir -p "$RUN_DIR"
    sudo touch "$RUN_DIR/ap-boot-delay"
    sleep "$AP_BOOT_DELAY_SECS"
    sudo rm -f "$RUN_DIR/ap-boot-delay"
fi

list_wlans() {
    local i
    for i in $(ls /sys/class/net 2>/dev/null | grep -E '^wlan[0-9]+$' | sort -V); do
        echo "$i"
    done
}

# USB dual-radio parked — helpers kept for when a dongle comes back.
# is_usb_wlan() {
#     local iface=$1 subs
#     [ -e "/sys/class/net/$iface" ] || return 1
#     subs=$(readlink -f "/sys/class/net/$iface/device/subsystem" 2>/dev/null) || return 1
#     [[ "$subs" == *usb* ]] && return 0
#     return 1
# }
#
# find_usb_wlan() {
#     local w
#     for w in $(list_wlans); do
#         is_usb_wlan "$w" && { echo "$w"; return 0; }
#     done
#     return 1
# }
#
# wait_for_usb_wlan() {
#     local w secs=${AP_PHYS_WAIT_SECS:-15} elapsed=0
#     if [ "$secs" -le 0 ] 2>/dev/null; then
#         find_usb_wlan
#         return $?
#     fi
#     while [ "$elapsed" -lt "$secs" ]; do
#         w=$(find_usb_wlan) && { echo "$w"; return 0; }
#         sleep 1
#         elapsed=$((elapsed + 1))
#     done
#     return 1
# }

resolve_ap_phys() {
    local w
    if [ -n "${AP_PHYS:-}" ] && [ "$AP_PHYS" != "auto" ]; then
        if [ -e "/sys/class/net/$AP_PHYS" ]; then
            echo "$AP_PHYS"
            return 0
        fi
        # USB dual-radio parked — was: special-case missing wlan1 / USB phy.
        # if is_usb_wlan "$AP_PHYS" 2>/dev/null || [ "$AP_PHYS" = "wlan1" ]; then
        #     echo "ERROR: AP_PHYS=$AP_PHYS (USB radio) not found — check dongle and aic8800 driver" >&2
        # else
        echo "ERROR: AP_PHYS=$AP_PHYS but /sys/class/net/$AP_PHYS not found" >&2
        # fi
        return 1
    fi
    # USB dual-radio parked — do not wait for a dongle. Always onboard.
    # Restore: uncomment the usb) case and use AP_PHYS_PREFER=usb in ap.conf.
    # case "${AP_PHYS_PREFER:-usb}" in
    #     usb)
    #         w=$(wait_for_usb_wlan) && { echo "$w"; return 0; }
    #         echo "No USB wlan after ${AP_PHYS_WAIT_SECS:-15}s wait; using onboard radio (single-radio AP)" >&2
    #         for w in $(list_wlans); do
    #             if ! is_usb_wlan "$w"; then echo "$w"; return 0; fi
    #         done
    #         ;;
    #     builtin)
    #         for w in $(list_wlans); do
    #             if ! is_usb_wlan "$w"; then echo "$w"; return 0; fi
    #         done
    #         ;;
    # esac
    w=$(list_wlans | head -n1)
    if [ -n "$w" ]; then
        echo "$w"
        return 0
    fi
    echo "ERROR: No wlan interface found" >&2
    return 1
}

LEDS_UNIT=fake-wifi-leds.service
LEDS_WERE_ACTIVE=0

# Bringing the radio up spikes 5V draw, and the strip runs off the Pi's own rail.
# Together they browned the board out mid-switch, so go dark for those few seconds.
quiesce_leds() {
    if systemctl is-active --quiet "$LEDS_UNIT"; then
        LEDS_WERE_ACTIVE=1
        echo "Pausing status LEDs across the radio switch (5V headroom)..."
        sudo systemctl stop "$LEDS_UNIT" 2>/dev/null || true
        sleep 1
    fi
}

resume_leds() {
    if [ "$LEDS_WERE_ACTIVE" = "1" ]; then
        LEDS_WERE_ACTIVE=0
        sudo systemctl start "$LEDS_UNIT" 2>/dev/null || true
    fi
}

on_exit() {
    resume_leds
    sudo rm -f "$STARTING_FLAG" 2>/dev/null || true
}

release_home_wifi() {
    local phy=$1 conn
    echo "Single-radio: releasing NetworkManager on $phy (home Wi-Fi will drop)..."
    conn=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
        | awk -F: -v d="$phy" '$2 == d { print $1; exit }')
    sudo mkdir -p "$RUN_DIR"
    if [ -n "$conn" ]; then
        echo "$conn" | sudo tee "$RUN_DIR/home-conn" > /dev/null
        echo "  Saved home connection: $conn"
    else
        sudo rm -f "$RUN_DIR/home-conn"
        echo "  No active NM connection on $phy"
    fi
    trap '' HUP
    sudo nmcli device disconnect "$phy" 2>/dev/null || true
    sudo nmcli device set "$phy" managed no 2>/dev/null || true
    sleep 1
}

detach_single_radio_if_needed() {
    local phy=$1
    # USB dual-radio parked — USB phy used to skip this (home Wi-Fi stayed up).
    # if is_usb_wlan "$phy"; then
    #     return 0
    # fi
    if [ -n "${INVOCATION_ID:-}" ] || [ -n "${FAKE_WIFI_DETACHED:-}" ]; then
        return 0
    fi
    if [ -z "${SSH_CONNECTION:-}" ]; then
        return 0
    fi
    echo "Single-radio start would drop this SSH session — continuing via systemd..."
    echo "  Join BURNER-NET.COM shortly, then: ssh j@192.168.4.1"
    sudo systemd-run \
        --unit=fake-wifi-ap-manual \
        --collect \
        --property=Type=oneshot \
        --property=RemainAfterExit=yes \
        --setenv=FAKE_WIFI_DETACHED=1 \
        /usr/local/bin/start-ap.sh
    # The re-exec owns the run-state now; don't tear down what it just set up.
    trap - EXIT
    exit 0
}

# Runtime hostapd/dnsmasq configs (onboard wlan0; uap0 was USB dual-radio).
write_runtime_configs() {
    local iface=$1
    sudo mkdir -p "$RUN_DIR"
    if [ -f /etc/hostapd/hostapd.conf ]; then
        sudo sed -E "s/^interface=.*/interface=$iface/" /etc/hostapd/hostapd.conf \
            | sudo tee "$HOSTAPD_RUN" > /dev/null
    else
        echo "ERROR: /etc/hostapd/hostapd.conf missing" >&2
        return 1
    fi
    if [ -f /etc/dnsmasq.conf ]; then
        sudo sed -E "s/^interface=.*/interface=$iface/" /etc/dnsmasq.conf \
            | sudo tee "$DNSMASQ_RUN" > /dev/null
    else
        echo "ERROR: /etc/dnsmasq.conf missing" >&2
        return 1
    fi
    echo "$iface" | sudo tee "$RUN_DIR/ap-iface" > /dev/null
}

ensure_ap_addr() {
    local iface=$1
    sudo ip link set "$iface" up || true
    sudo ip addr replace 192.168.4.1/24 dev "$iface"
    sleep 1
    if ! ip -4 -br addr show "$iface" 2>/dev/null | grep -q '192\.168\.4\.1'; then
        echo "ERROR: $iface missing 192.168.4.1" >&2
        ip -br link show "$iface" >&2 || true
        ip -br addr show "$iface" >&2 || true
        return 1
    fi
    echo "✓ $iface has 192.168.4.1/24 ($(ip -br link show "$iface" | awk '{print $2}'))"
}

start_hostapd_runtime() {
    sudo systemctl stop hostapd 2>/dev/null || true
    sudo systemctl unmask hostapd 2>/dev/null || true
    # Bypass unit ConfPath so we can point at the runtime interface file
    if sudo hostapd -B "$HOSTAPD_RUN"; then
        sleep 2
        if pgrep -x hostapd >/dev/null; then
            echo "✓ hostapd is running ($(cat "$RUN_DIR/ap-iface"))"
            return 0
        fi
    fi
    echo "✗ hostapd failed to start"
    return 1
}

start_dnsmasq_runtime() {
    sudo systemctl stop dnsmasq 2>/dev/null || true
    sudo pkill -x dnsmasq 2>/dev/null || true
    sleep 0.5
    if sudo dnsmasq -C "$DNSMASQ_RUN"; then
        sleep 1
        if pgrep -x dnsmasq >/dev/null; then
            echo "✓ dnsmasq is running"
            return 0
        fi
    fi
    echo "✗ dnsmasq failed to start"
    return 1
}

block_dot() {
    local iface=$1
    if command -v iptables >/dev/null 2>&1; then
        echo "Adding iptables rule to reject DoT (port 853) on $iface..."
        sudo iptables -D INPUT -i "$iface" -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
        sudo iptables -I INPUT -i "$iface" -p tcp --dport 853 -j REJECT --reject-with tcp-reset || true
        sudo iptables -D FORWARD -i "$iface" -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
        sudo iptables -I FORWARD -i "$iface" -p tcp --dport 853 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    elif command -v nft >/dev/null 2>&1; then
        echo "Adding nftables rule to reject DoT (port 853) on $iface..."
        sudo nft add table inet fakewifi 2>/dev/null || true
        sudo nft 'add chain inet fakewifi input { type filter hook input priority 0 ; }' 2>/dev/null || true
        sudo nft flush chain inet fakewifi input 2>/dev/null || true
        sudo nft add rule inet fakewifi input iifname "$iface" tcp dport 853 reject with tcp reset || true
    else
        echo "WARNING: neither iptables nor nft found — Private DNS (port 853) NOT blocked."
    fi
}

{
    echo "=========================================="
    echo "AP Start Log - $(date)"
    echo "=========================================="

    # Tell the LEDs we're coming up so they show "starting" rather than off-air red.
    sudo mkdir -p "$RUN_DIR"
    sudo touch "$STARTING_FLAG"
    trap on_exit EXIT

    PHY=$(resolve_ap_phys) || exit 1
    sudo mkdir -p "$RUN_DIR"
    echo "$PHY" | sudo tee "$RUN_DIR/ap-phy" > /dev/null

    echo "Using physical Wi-Fi: $PHY (from /etc/fake-wifi/ap.conf)"

    # USB dual-radio parked — uap0 on the dongle. Restore this whole branch.
    # if is_usb_wlan "$PHY"; then
    #     echo "Mode: dual-radio — AP on USB $PHY via uap0"
    #     quiesce_leds
    #     sudo rm -f "$RUN_DIR/home-conn"
    #     AP_IFACE=uap0
    #     echo "Creating virtual AP interface uap0..."
    #     sudo iw dev uap0 del 2>/dev/null || true
    #     sudo iw dev "$PHY" interface add uap0 type __ap
    #     sudo rfkill unblock wlan 2>/dev/null || true
    #     sudo ip link set uap0 up
    #     sudo ip addr add 192.168.4.1/24 dev uap0 2>/dev/null || sudo ip addr replace 192.168.4.1/24 dev uap0
    # else
        echo "Mode: single-radio — hostapd directly on $PHY (no uap0; brcmfmac-safe)"
        detach_single_radio_if_needed "$PHY"
        quiesce_leds
        release_home_wifi "$PHY"
        AP_IFACE=$PHY

        # Ensure no stale uap0 from a previous dual-radio run
        sudo iw dev uap0 del 2>/dev/null || true
        sudo rfkill unblock wlan 2>/dev/null || true
        sudo ip link set "$PHY" up
        # Drop any prior STA addresses before assigning portal IP
        sudo ip addr flush dev "$PHY" 2>/dev/null || true
        sudo ip addr replace 192.168.4.1/24 dev "$PHY"
    # fi

    write_runtime_configs "$AP_IFACE"

    echo "Starting hostapd on $AP_IFACE..."
    start_hostapd_runtime || exit 1

    echo "Re-applying AP address after hostapd..."
    ensure_ap_addr "$AP_IFACE"

    echo "Starting dnsmasq on $AP_IFACE..."
    start_dnsmasq_runtime || exit 1

    block_dot "$AP_IFACE"

    echo "Starting post board API..."
    sudo systemctl start burnernet-api.service 2>/dev/null || true

    echo "Ensuring SSH is accessible..."
    sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow 22/tcp 2>/dev/null || true
    fi

    resume_leds

    echo ""
    echo "=========================================="
    echo "AP started! SSID: BURNER-NET.COM on $AP_IFACE"
    echo ""
    # USB dual-radio parked — dual-radio success text lived here.
    # if is_usb_wlan "$PHY"; then
    #     echo "Dual-radio: onboard keeps home Wi-Fi / SSH."
    #     echo "Or join BURNER-NET.COM → ssh j@192.168.4.1"
    # else
        echo "Single-radio: home Wi-Fi is down — SSH: j@192.168.4.1"
        echo "stop-ap.sh restores the saved home network."
    # fi
    echo "=========================================="
    echo "Log saved to: $LOG_FILE"
} | tee -a "$LOG_FILE"
