#!/usr/bin/env bash
# Copies the website's static files into nginx's docroot and reloads.
# Run this after editing anything under website/ to publish changes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 build_log.py
python3 build_roadmap.py
python3 build_weekly.py
python3 build_feed.py
python3 build_sitemap.py

# Publish everything except status.html first: build_status.py's page-health
# check curls localhost, so a newly-added page must already be live before
# that check runs or it reports a false failure on its own first deploy.
sudo -n cp index.html log.html weekly.html roadmap.html build.html field-guide.html memory-handbook.html study-guide.html getting-started.html service-desk.html service-desk-mockup.html service-desk-integration-guide.html agent-protocol.html soc-architecture.html ticket-trace.html operations-sop.html service-desk-deployment-guide.pdf service-desk-integration-guide.pdf operations-sop.pdf service-desk-architecture.pptx faq.html get.html style.css reveal.js favicon.svg favicon.ico og-image.png apple-touch-icon.png feed.atom robots.txt sitemap.xml /var/www/html/
sudo -n chown root:root /var/www/html/index.html /var/www/html/log.html /var/www/html/weekly.html /var/www/html/roadmap.html /var/www/html/build.html /var/www/html/field-guide.html /var/www/html/memory-handbook.html /var/www/html/study-guide.html /var/www/html/getting-started.html /var/www/html/service-desk.html /var/www/html/service-desk-mockup.html /var/www/html/service-desk-integration-guide.html /var/www/html/agent-protocol.html /var/www/html/soc-architecture.html /var/www/html/ticket-trace.html /var/www/html/operations-sop.html /var/www/html/service-desk-deployment-guide.pdf /var/www/html/service-desk-integration-guide.pdf /var/www/html/operations-sop.pdf /var/www/html/service-desk-architecture.pptx /var/www/html/faq.html /var/www/html/get.html /var/www/html/style.css /var/www/html/reveal.js /var/www/html/favicon.svg /var/www/html/favicon.ico /var/www/html/og-image.png /var/www/html/apple-touch-icon.png /var/www/html/feed.atom /var/www/html/robots.txt /var/www/html/sitemap.xml

python3 build_status.py
sudo -n cp status.html /var/www/html/
sudo -n chown root:root /var/www/html/status.html

sudo -n nginx -t
sudo -n systemctl reload nginx
echo "Deployed. Live at https://www.beaconwake.com/"
