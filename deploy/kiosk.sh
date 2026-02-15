#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://localhost:8080}"

chromium-browser \
  --kiosk \
  --incognito \
  --noerrdialogs \
  --disable-infobars \
  --check-for-update-interval=31536000 \
  "$URL"
