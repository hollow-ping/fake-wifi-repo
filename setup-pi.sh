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

# Get the actual user (not root if running with sudo)
REAL_USER=${SUDO_USER:-$USER}
if [ "$REAL_USER" = "root" ] || [ -z "$REAL_USER" ]; then
    REAL_USER=$(who am i | awk '{print $1}' 2>/dev/null || echo "pi")
fi

# Install packages
sudo apt update
sudo apt install -y hostapd dnsmasq lighttpd iptables-persistent

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

# Set up captive portal detection files
if [ -f /home/$REAL_USER/fake-wifi-repo/captive-portal-files/hotspot-detect.html ]; then
    sudo cp /home/$REAL_USER/fake-wifi-repo/captive-portal-files/hotspot-detect.html /var/www/html/hotspot-detect.html
else
    sudo sh -c 'echo "<!DOCTYPE html><html><head><meta http-equiv=\"refresh\" content=\"0; url=/\"><title>Success</title></head><body><script>window.location.href=\"/\";</script></body></html>" > /var/www/html/hotspot-detect.html'
fi

if [ -f /home/$REAL_USER/fake-wifi-repo/captive-portal-files/generate_204 ]; then
    sudo cp /home/$REAL_USER/fake-wifi-repo/captive-portal-files/generate_204 /var/www/html/generate_204
else
    sudo sh -c 'echo "HTTP/1.1 204 No Content" > /var/www/html/generate_204'
fi

if [ -f /home/$REAL_USER/fake-wifi-repo/captive-portal-files/connecttest.txt ]; then
    sudo cp /home/$REAL_USER/fake-wifi-repo/captive-portal-files/connecttest.txt /var/www/html/connecttest.txt
else
    sudo sh -c 'echo "Microsoft Connect Test" > /var/www/html/connecttest.txt'
fi

# Fix permissions for web server
sudo chown -R www-data:www-data /var/www/html/
sudo chmod -R 755 /var/www/html/
sudo find /var/www/html -type f -exec chmod 644 {} \;

# Configure hostapd (but don't enable auto-start)
# Using uap0 virtual interface so wlan0 can stay connected for SSH
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=uap0
driver=nl80211
ssid=BurnerNet-Portal
hw_mode=g
channel=7
wmm_enabled=0
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
address=/#/192.168.4.1
address=/burner-net.com/192.168.4.1
# Captive portal detection domains
address=/captive.apple.com/192.168.4.1
address=/connectivitycheck.gstatic.com/192.168.4.1
address=/www.msftconnecttest.com/192.168.4.1
EOF

# Create start/stop scripts
sudo tee /usr/local/bin/start-ap.sh > /dev/null <<'SCRIPT'
#!/bin/bash
set -e

LOG_FILE="/var/log/ap-start.log"
mkdir -p /var/log

{
    echo "=========================================="
    echo "AP Start Log - $(date)"
    echo "=========================================="
    
    echo "Creating virtual AP interface uap0..."
    # Remove uap0 if it exists
    sudo iw dev uap0 del 2>/dev/null || true
    # Create uap0 as virtual AP interface from wlan0
    sudo iw dev wlan0 interface add uap0 type __ap
    
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
    
    echo "Starting dnsmasq..."
    sudo systemctl start dnsmasq

    echo "Configuring iptables for captive portal..."
    # Belt-and-suspenders: redirect all HTTP on AP interface to our portal even if DNS lags
    iptables -t nat -D PREROUTING -i uap0 -p tcp --dport 80 -j DNAT --to-destination 192.168.4.1:80 2>/dev/null || true
    iptables -t nat -A PREROUTING -i uap0 -p tcp --dport 80 -j DNAT --to-destination 192.168.4.1:80
    # Reject HTTPS fast so phones don't wait for timeout before HTTP captive portal probe
    iptables -D INPUT -i uap0 -p tcp --dport 443 -j REJECT --reject-with tcp-reset 2>/dev/null || true
    iptables -A INPUT -i uap0 -p tcp --dport 443 -j REJECT --reject-with tcp-reset
    # Persist rules across reboots
    netfilter-persistent save 2>/dev/null || true
    echo "✓ iptables configured"

    echo "Ensuring SSH is accessible..."
    sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true
    
    echo "Checking firewall (ufw)..."
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow 22/tcp 2>/dev/null || true
        echo "  SSH port 22 allowed"
    fi
    
    echo ""
    echo "=========================================="
    echo "AP started! SSID: BurnerNet-Portal"
    echo ""
    echo "wlan0 remains connected for SSH access!"
    echo "uap0 is broadcasting the AP."
    echo ""
    echo "You can SSH via your regular WiFi (wlan0) OR"
    echo "connect to 'BurnerNet-Portal' and SSH to j@192.168.4.1"
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
sudo ip addr del 192.168.4.1/24 dev uap0 2>/dev/null || true
sudo ip link set uap0 down 2>/dev/null || true
sudo iw dev uap0 del 2>/dev/null || true
# Clean up iptables rules
iptables -t nat -D PREROUTING -i uap0 -p tcp --dport 80 -j DNAT --to-destination 192.168.4.1:80 2>/dev/null || true
iptables -D INPUT -i uap0 -p tcp --dport 443 -j REJECT --reject-with tcp-reset 2>/dev/null || true
echo "AP stopped. Virtual interface uap0 removed."
echo "wlan0 remains connected for SSH access."
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

# Unmask hostapd (in case it was masked) but don't enable auto-start
sudo systemctl unmask hostapd 2>/dev/null || true
sudo systemctl disable hostapd
sudo systemctl disable dnsmasq

# Configure lighttpd to redirect all requests to portal
# Backup original config
sudo cp /etc/lighttpd/lighttpd.conf /etc/lighttpd/lighttpd.conf.backup 2>/dev/null || true

# Add URL rewriting to redirect all non-file requests to index.html
if ! grep -q "captive-portal" /etc/lighttpd/lighttpd.conf; then
    sudo tee -a /etc/lighttpd/lighttpd.conf > /dev/null <<'LIGHTTPD_CONFIG'

# Captive portal configuration
server.modules += ( "mod_rewrite", "mod_redirect" )

# Captive portal probe paths - return 302 to portal so all OSes trigger their browser
# iOS probes: hotspot-detect.html, library/test/success.html
# Android probes: generate_204, check_network_status.txt
# Windows probes: connecttest.txt, ncsi.txt
# Firefox: success.txt
$HTTP["url"] =~ "^/(hotspot-detect\.html|generate_204|ncsi\.txt|connecttest\.txt|success\.txt|check_network_status\.txt)" {
    url.redirect = ("^/.*$" => "http://192.168.4.1/")
}

# Rewrite any other non-file request to the portal
$HTTP["url"] !~ "^/(index\.html|.*\.(html|css|js|jpg|jpeg|png|gif|ico|json|txt|pdf|svg|woff|woff2|ttf|eot|mp4|webm|map))" {
    url.rewrite-once = (
        "^/(.*)" => "/index.html"
    )
}
LIGHTTPD_CONFIG
fi

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
Description=Fake WiFi Access Point (BurnerNet-Portal)
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

# Enable the service to start on boot
sudo systemctl daemon-reload
sudo systemctl enable fake-wifi-ap.service

echo ""
echo "=========================================="
echo "Setup complete!"
echo ""
echo "To start AP: sudo start-ap.sh"
echo "To stop AP:  sudo stop-ap.sh"
echo "To view logs: view-ap-log.sh"
echo ""
echo "✓ Auto-start enabled: AP will start on boot"
echo "  (waits for network, so wlan0 connects to 'pacsun' first)"
echo ""
echo "Note: wlan0 stays connected for SSH access!"
echo "      uap0 broadcasts 'BurnerNet-Portal' AP"
echo ""
echo "Logs are saved to: /var/log/ap-start.log"
echo "=========================================="