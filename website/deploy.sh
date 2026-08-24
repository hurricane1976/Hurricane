#!/usr/bin/env bash
# Copies the website's static files into nginx's docroot and reloads.
# Run this after editing anything under website/ to publish changes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 build_log.py

sudo -n cp index.html log.html style.css favicon.svg /var/www/html/
sudo -n chown root:root /var/www/html/index.html /var/www/html/log.html /var/www/html/style.css /var/www/html/favicon.svg
sudo -n nginx -t
sudo -n systemctl reload nginx
echo "Deployed. Live at http://$(curl -s -4 --max-time 5 ifconfig.me)/"
