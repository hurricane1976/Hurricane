#!/usr/bin/env bash
# Copies website/index.html into nginx's docroot and reloads.
# Run this after editing website/index.html to publish changes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

sudo -n cp index.html /var/www/html/index.html
sudo -n chown root:root /var/www/html/index.html
sudo -n nginx -t
sudo -n systemctl reload nginx
echo "Deployed. Live at http://$(curl -s -4 --max-time 5 ifconfig.me)/"
