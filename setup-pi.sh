#!/bin/bash
# Run this once on your Pi to set everything up

# Then `sudo start-ap.sh` to start the AP
# Then `sudo stop-ap.sh` to stop the AP
# On the AP, to connect, do `ssh john@192.168.4.1`

# Install packages
sudo apt update
sudo apt install -y hostapd dnsmasq lighttpd

# Copy your files
sudo rm -rf /var/www/html/*
sudo cp -r /home/$USER/fake-wifi-repo/* /var/www/html/

# Configure hostapd (but don't enable auto-start)
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=wlan0
driver=nl80211
ssid=BurnerNet-Portal
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
EOF

# Configure dnsmasq
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.backup
sudo tee /etc/dnsmasq.conf > /dev/null <<EOF
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/192.168.4.1
address=/burner-net.com/192.168.4.1
EOF

# Create start/stop scripts
sudo tee /usr/local/bin/start-ap.sh > /dev/null <<'SCRIPT'
#!/bin/bash
sudo systemctl stop wpa_supplicant
sudo ip addr add 192.168.4.1/24 dev wlan0
sudo systemctl start hostapd
sudo systemctl start dnsmasq
echo "AP started! SSID: BurnerNet-Portal"
SCRIPT

sudo tee /usr/local/bin/stop-ap.sh > /dev/null <<'SCRIPT'
#!/bin/bash
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
sudo ip addr del 192.168.4.1/24 dev wlan0 2>/dev/null
sudo systemctl start wpa_supplicant
echo "AP stopped. WiFi client mode restored."
SCRIPT

sudo chmod +x /usr/local/bin/start-ap.sh /usr/local/bin/stop-ap.sh

# Make sure services DON'T auto-start
sudo systemctl disable hostapd
sudo systemctl disable dnsmasq

# Enable lighttpd (web server always runs)
sudo systemctl enable lighttpd
sudo systemctl start lighttpd

echo "Setup complete! To start AP: sudo start-ap.sh"
echo "To stop AP: sudo stop-ap.sh"