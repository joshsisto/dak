#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
ENABLE_KIOSK="${ENABLE_KIOSK:-1}"

APP_SERVICE_NAME="pi-dashboard.service"
KIOSK_SERVICE_NAME="pi-dashboard-kiosk.service"

render_unit() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|{{APP_USER}}|${APP_USER}|g" \
    -e "s|{{APP_DIR}}|${APP_DIR}|g" \
    "${src}" | sudo tee "${dst}" >/dev/null
}

echo "Using APP_DIR=${APP_DIR}"
echo "Using APP_USER=${APP_USER}"
echo "Kiosk enabled: ${ENABLE_KIOSK}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

if [ ! -d "${APP_DIR}/.venv" ]; then
  python3 -m venv "${APP_DIR}/.venv"
fi

"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [ ! -f "${APP_DIR}/.env" ]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from template. Update it with your real values."
fi

render_unit "${APP_DIR}/deploy/pi-dashboard.service" "/etc/systemd/system/${APP_SERVICE_NAME}"

if [ "${ENABLE_KIOSK}" = "1" ]; then
  render_unit "${APP_DIR}/deploy/pi-dashboard-kiosk.service" "/etc/systemd/system/${KIOSK_SERVICE_NAME}"
fi

sudo systemctl daemon-reload
sudo systemctl enable --now "${APP_SERVICE_NAME}"

if [ "${ENABLE_KIOSK}" = "1" ]; then
  sudo systemctl enable --now "${KIOSK_SERVICE_NAME}" || true
fi

echo
echo "Service status:"
sudo systemctl --no-pager --full status "${APP_SERVICE_NAME}" | sed -n '1,40p'
if [ "${ENABLE_KIOSK}" = "1" ]; then
  sudo systemctl --no-pager --full status "${KIOSK_SERVICE_NAME}" | sed -n '1,40p' || true
fi

echo
echo "Dashboard URL:"
echo "http://$(hostname -I | awk '{print $1}'):8080"
