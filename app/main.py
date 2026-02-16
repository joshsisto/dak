from __future__ import annotations

import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, send_from_directory

from app.config import Settings
from app.services.calendar import CalendarService
from app.services.photos import PhotoService
from app.services.time_service import TimeService
from app.services.weather import WeatherService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def create_app() -> Flask:
    load_dotenv()
    settings = Settings.from_env()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["settings"] = settings

    calendar_service = CalendarService(settings)
    weather_service = WeatherService(settings)
    photo_service = PhotoService(settings)
    time_service = TimeService(settings)

    @app.get("/")
    def index():
        return render_template("index.html", settings=settings)

    @app.get("/api/dashboard")
    def dashboard_data():
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calendar": [],
            "calendars": {
                "combined": [],
                "by_calendar": [],
                "errors": [],
                "month_view": {},
            },
            "weather": {},
            "photos": [],
            "time": {},
            "errors": [],
        }

        try:
            calendar_payload = calendar_service.upcoming_events()
            payload["calendar"] = calendar_payload.get("combined", [])
            payload["calendars"] = calendar_payload
            for item in calendar_payload.get("errors", []):
                name = item.get("calendar_name", "unknown")
                message = item.get("message", "Unknown error")
                payload["errors"].append(f"calendar[{name}]: {message}")
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to fetch calendar data")
            payload["errors"].append(f"calendar: {exc}")

        try:
            payload["weather"] = weather_service.forecast()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to fetch weather data")
            payload["errors"].append(f"weather: {exc}")

        try:
            payload["photos"] = photo_service.list_photos()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to fetch photo data")
            payload["errors"].append(f"photos: {exc}")

        try:
            payload["time"] = time_service.snapshot()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to fetch time data")
            payload["errors"].append(f"time: {exc}")

        return jsonify(payload)

    @app.get("/media/<path:filename>")
    def media(filename: str):
        if not settings.photos_directory.exists():
            abort(404)
        return send_from_directory(str(settings.photos_directory), filename)

    @app.get("/moon-cache/<path:filename>")
    def moon_cache(filename: str):
        if not settings.moon_cache_directory.exists():
            abort(404)
        return send_from_directory(str(settings.moon_cache_directory), filename)

    return app


app = create_app()


if __name__ == "__main__":
    runtime_settings: Settings = app.config.get("settings", Settings.from_env())
    app.run(host=runtime_settings.host, port=runtime_settings.port, debug=False)
