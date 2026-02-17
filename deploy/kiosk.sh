#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://localhost:8080}"
DISPLAY="${DISPLAY:-:0}"
export DISPLAY

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi

wait_for() {
  local description="$1"
  local cmd="$2"
  local retries="${3:-90}"
  local sleep_seconds="${4:-2}"
  local attempt=1
  while [ "${attempt}" -le "${retries}" ]; do
    if eval "${cmd}" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep "${sleep_seconds}"
  done
  echo "Timed out waiting for ${description}" >&2
  return 1
}

wait_for "dashboard backend at ${URL}" "curl -fsS '${URL}'"
wait_for "display server on ${DISPLAY}" "xset q"

if command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium"
else
  echo "Could not find chromium-browser or chromium in PATH." >&2
  exit 1
fi

exec "${CHROMIUM_BIN}" \
  --kiosk \
  --incognito \
  --noerrdialogs \
  --disable-infobars \
  --check-for-update-interval=31536000 \
  --disable-session-crashed-bubble \
  --no-first-run \
  --no-default-browser-check \
  "$URL"
