#!/bin/bash
# Copy sponsored ads from repo home → live portal. Run on Pi:
#   sudo /usr/local/bin/deploy-www-ads.sh
# Or from Mac after rsync:
#   ssh -t j@jw1.local 'sudo /usr/local/bin/deploy-www-ads.sh'
set -euo pipefail

SRC="${1:-/home/j/fake-wifi-repo/connect/ads}"
DST="/var/www/html/connect/ads"

install -d -m 755 "$DST"
cp "$SRC"/ad*.jpg "$DST"/
chown www-data:www-data "$DST"/*.jpg
chmod 644 "$DST"/*.jpg
echo "Deployed ads to $DST:"
ls -la "$DST"
