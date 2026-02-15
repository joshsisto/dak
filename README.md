# Raspberry Pi DAK-style Dashboard (Python)

This project is a self-hosted wallboard app you can run on a Raspberry Pi.

Current MVP features:
- iCloud shared calendar events (single or multiple public ICS URLs)
- Combined upcoming events list (with per-calendar color badges)
- Calendar ICS caching (12-hour default) to reduce iCloud requests
- Human-readable calendar event export file
- Server-time clock with seconds (NTP-backed on host OS)
- Weather from Open-Meteo
- Shared photos from:
  - iCloud Shared Album public URL, or
  - local directory fallback
- 1920x1080-optimized dashboard layout (large top weather/time, wider photo area)

## Stack
- Flask backend + server-rendered dashboard
- Small JS frontend polling `/api/dashboard`
- Python services for calendar/weather/photos/time

## Quick Start
1. Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
```
Then edit `.env` with your values.

4. Run:
```bash
python -m app.main
```

5. Open:
`http://<pi-ip>:8080`

## Required Config
- `CALENDAR_SOURCES`: preferred multi-calendar config in format `Name|ICS_URL;Name2|ICS_URL2`.
- `CALENDAR_ICS_URL`: legacy single-calendar fallback (still supported).
- `CALENDAR_CACHE_SECONDS`: ICS cache TTL (default `43200` / 12h).
- `CALENDAR_CACHE_DIRECTORY`: where cached ICS files are stored.
- `CALENDAR_EVENTS_TEXT_FILE`: output text file for readable event export.
- `DISPLAY_TIMEZONE`: timezone used for event labels and displayed clock.
- `WEATHER_LATITUDE` / `WEATHER_LONGITUDE`: your location for weather.
- `PHOTOS_SOURCE`: `icloud_shared_album` or `directory`.
- `ICLOUD_SHARED_ALBUM_URL`: required for iCloud photos.
- `PHOTOS_DIRECTORY`: used when `PHOTOS_SOURCE=directory` or as fallback.

## Raspberry Pi Kiosk Setup
Run this once on the Pi to install dependencies and enable boot services:
```bash
cd ~/codex
./deploy/install_on_pi.sh
```

What this script does:
- creates/updates `.venv`
- installs `requirements.txt`
- creates `.env` from `.env.example` if missing
- installs and enables `pi-dashboard.service` (backend on boot)
- installs and enables `pi-dashboard-kiosk.service` (Chromium kiosk on boot, optional)

Options:
- disable kiosk service:
```bash
ENABLE_KIOSK=0 ./deploy/install_on_pi.sh
```
- override app path/user if needed:
```bash
APP_DIR=/home/pi/codex APP_USER=pi ./deploy/install_on_pi.sh
```

Manual service commands:
```bash
sudo systemctl restart pi-dashboard
sudo systemctl status pi-dashboard
sudo journalctl -u pi-dashboard -f
```

Kiosk service logs:
```bash
sudo systemctl status pi-dashboard-kiosk
sudo journalctl -u pi-dashboard-kiosk -f
```

## API Notes
- `/api/dashboard` returns:
  - `calendars.combined`: upcoming merged events (used by UI)
  - `calendars.by_calendar`: per-calendar upcoming events (returned, currently hidden in UI)
  - `calendars.month_view`: month grid payload (returned, currently hidden in UI)
  - `time`: server clock snapshot and NTP sync status

## Calendar Cache + Export
- Calendar ICS URLs are fetched at most once per cache window (`CALENDAR_CACHE_SECONDS`, default 12 hours).
- On network failure, stale cached ICS is used when available.
- A readable event report is written to `CALENDAR_EVENTS_TEXT_FILE` and updated as events change.

## Notes / Limitations
- iCloud Shared Album integration uses undocumented Apple sharedstreams endpoints.
- If Apple changes the endpoint behavior, photo mode may break; local directory mode still works.
- Calendar recurring events are expanded using `recurring-ical-events`.
