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
python3 build_agent_manifest.py
python3 build_fleet_status.py
python3 build_metrics.py

# Gate 1: static checks on the freshly-built files before they overwrite
# anything in the docroot (small/truncated pages, unclosed HTML, internal
# links pointing at files that don't exist).
python3 smoke_test.py --local

# Publish everything except status.html first: build_status.py's page-health
# check curls localhost, so a newly-added page must already be live before
# that check runs or it reports a false failure on its own first deploy.
sudo -n cp index.html log.html weekly.html roadmap.html build.html field-guide.html memory-handbook.html study-guide.html guides.html claude-code-headless.html claude-code-cron.html claude-code-permissions.html claude-code-memory.html fleet-status.html fleet.json metrics.html getting-started.html service-desk.html service-desk-mockup.html service-desk-integration-guide.html agent-protocol.html distributed-agents.html soc-architecture.html ticket-trace.html operations-sop.html agent-ops.html architecture-review.html service-desk-deployment-guide.pdf service-desk-integration-guide.pdf operations-sop.pdf service-desk-architecture.pptx faq.html agora.html get.html style.css reveal.js favicon.svg favicon.ico og-image.png og-agora.png og-soc.png og-distributed.png og-claude-code-headless.png og-claude-code-cron.png og-claude-code-permissions.png apple-touch-icon.png feed.atom robots.txt sitemap.xml /var/www/html/
sudo -n chown root:root /var/www/html/index.html /var/www/html/log.html /var/www/html/weekly.html /var/www/html/roadmap.html /var/www/html/build.html /var/www/html/field-guide.html /var/www/html/memory-handbook.html /var/www/html/study-guide.html /var/www/html/guides.html /var/www/html/claude-code-headless.html /var/www/html/claude-code-cron.html /var/www/html/claude-code-permissions.html /var/www/html/claude-code-memory.html /var/www/html/fleet-status.html /var/www/html/fleet.json /var/www/html/metrics.html /var/www/html/getting-started.html /var/www/html/service-desk.html /var/www/html/service-desk-mockup.html /var/www/html/service-desk-integration-guide.html /var/www/html/agent-protocol.html /var/www/html/distributed-agents.html /var/www/html/soc-architecture.html /var/www/html/ticket-trace.html /var/www/html/operations-sop.html /var/www/html/agent-ops.html /var/www/html/architecture-review.html /var/www/html/service-desk-deployment-guide.pdf /var/www/html/service-desk-integration-guide.pdf /var/www/html/operations-sop.pdf /var/www/html/service-desk-architecture.pptx /var/www/html/faq.html /var/www/html/agora.html /var/www/html/get.html /var/www/html/style.css /var/www/html/reveal.js /var/www/html/favicon.svg /var/www/html/favicon.ico /var/www/html/og-image.png /var/www/html/og-agora.png /var/www/html/og-soc.png /var/www/html/og-distributed.png /var/www/html/og-claude-code-headless.png /var/www/html/og-claude-code-cron.png /var/www/html/og-claude-code-permissions.png /var/www/html/apple-touch-icon.png /var/www/html/feed.atom /var/www/html/robots.txt /var/www/html/sitemap.xml

# Machine-discovery files under /.well-known/ (agent.json manifest + RFC 9116
# security.txt). deploy.sh copies an explicit file list, so the dotdir needs an
# explicit mkdir + cp -- rsync's dotfile behaviour doesn't apply here. Publish
# these BEFORE build_status.py, same reason as the block above: its page-health
# check curls localhost and would 404 a not-yet-published path.
sudo -n mkdir -p /var/www/html/.well-known
sudo -n cp .well-known/agent.json .well-known/security.txt /var/www/html/.well-known/
sudo -n chown -R root:root /var/www/html/.well-known

python3 build_status.py
sudo -n cp status.html /var/www/html/
sudo -n chown root:root /var/www/html/status.html

sudo -n nginx -t

# Gate 2: every tracked page/endpoint must return 200 from the docroot
# before we reload. Files are already on disk and served per-request, so
# this tests the just-published content; a failure aborts (set -e) loudly
# instead of shipping a broken page in silence.
python3 smoke_test.py --live

sudo -n systemctl reload nginx
echo "Deployed. Live at https://www.beaconwake.com/"
