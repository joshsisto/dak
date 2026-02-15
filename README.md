# Raspberry Pi DAK-style Dashboard (Python)

This project is a self-hosted wallboard app you can run on a Raspberry Pi.

Current MVP features:
- iCloud shared calendar events (single or multiple public ICS URLs)
- Combined upcoming events list (with per-calendar color badges)
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
- `DISPLAY_TIMEZONE`: timezone used for event labels and displayed clock.
- `WEATHER_LATITUDE` / `WEATHER_LONGITUDE`: your location for weather.
- `PHOTOS_SOURCE`: `icloud_shared_album` or `directory`.
- `ICLOUD_SHARED_ALBUM_URL`: required for iCloud photos.
- `PHOTOS_DIRECTORY`: used when `PHOTOS_SOURCE=directory` or as fallback.

## Raspberry Pi Kiosk Setup
Install Chromium and auto-start in kiosk mode:
```bash
chromium-browser --kiosk --incognito --noerrdialogs http://localhost:8080
```

Run the Flask app as a service (recommended) with `systemd`, then launch Chromium on login.

Example `systemd` unit is included at `deploy/pi-dashboard.service`.

Install it on Pi:
```bash
sudo cp deploy/pi-dashboard.service /etc/systemd/system/pi-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now pi-dashboard.service
sudo systemctl status pi-dashboard.service
```

Kiosk helper script is included at `deploy/kiosk.sh`.

## API Notes
- `/api/dashboard` returns:
  - `calendars.combined`: upcoming merged events (used by UI)
  - `calendars.by_calendar`: per-calendar upcoming events (returned, currently hidden in UI)
  - `calendars.month_view`: month grid payload (returned, currently hidden in UI)
  - `time`: server clock snapshot and NTP sync status

## Notes / Limitations
- iCloud Shared Album integration uses undocumented Apple sharedstreams endpoints.
- If Apple changes the endpoint behavior, photo mode may break; local directory mode still works.
- Calendar recurring events are expanded using `recurring-ical-events`.
