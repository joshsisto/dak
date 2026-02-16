from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from app.config import Settings


WEATHER_CODE_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _weather_icon(code: int, is_day: bool) -> str:
    if code == 0:
        return "☀" if is_day else "☾"
    if code in {1, 2, 3}:
        return "⛅" if is_day else "☁"
    if code in {45, 48}:
        return "🌫"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "🌧"
    if code in {71, 73, 75, 77, 85, 86}:
        return "❄"
    if code in {95, 96, 99}:
        return "⛈"
    return "•"


class WeatherService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()

    def forecast(self) -> dict[str, Any]:
        params = {
            "latitude": self._settings.weather_latitude,
            "longitude": self._settings.weather_longitude,
            "current": (
                "temperature_2m,apparent_temperature,is_day,weather_code,"
                "wind_speed_10m,relative_humidity_2m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,sunrise,sunset"
            ),
            "timezone": self._settings.weather_timezone,
            "temperature_unit": self._settings.weather_temperature_unit,
            "wind_speed_unit": self._settings.weather_wind_speed_unit,
            "forecast_days": 5,
        }
        response = self._session.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=self._settings.http_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        current = payload.get("current", {})
        daily = payload.get("daily", {})

        current_code = int(current.get("weather_code", 0))
        current_is_day = bool(current.get("is_day", 1))
        current_block = {
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "wind_speed": current.get("wind_speed_10m"),
            "humidity": current.get("relative_humidity_2m"),
            "description": WEATHER_CODE_DESCRIPTIONS.get(current_code, "Unknown"),
            "icon": _weather_icon(current_code, current_is_day),
            "time": current.get("time"),
        }

        daily_list: list[dict[str, Any]] = []
        days = daily.get("time", [])
        codes = daily.get("weather_code", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_probability_max", [])

        for index, day in enumerate(days):
            code = int(codes[index]) if index < len(codes) else 0
            day_date = datetime.fromisoformat(day)
            daily_list.append(
                {
                    "date": day,
                    "day_label": day_date.strftime("%a"),
                    "icon": _weather_icon(code, True),
                    "description": WEATHER_CODE_DESCRIPTIONS.get(code, "Unknown"),
                    "high": highs[index] if index < len(highs) else None,
                    "low": lows[index] if index < len(lows) else None,
                    "precip": precip[index] if index < len(precip) else None,
                }
            )

        sunrise_list = daily.get("sunrise", [])
        sunset_list = daily.get("sunset", [])
        sunrise = sunrise_list[0] if sunrise_list else None
        sunset = sunset_list[0] if sunset_list else None

        aqi_value = self._fetch_air_quality()
        moon = _moon_phase(datetime.now(timezone.utc))

        units = payload.get("current_units", {})
        return {
            "current": current_block,
            "daily": daily_list,
            "details": {
                "humidity": current.get("relative_humidity_2m"),
                "air_quality_index": aqi_value,
                "air_quality_label": _aqi_label(aqi_value),
                "sunrise": _format_local_time(sunrise),
                "sunset": _format_local_time(sunset),
                "moon_phase": moon["name"],
                "moon_icon": moon["icon"],
            },
            "temperature_unit": units.get("temperature_2m", "°"),
            "wind_speed_unit": units.get("wind_speed_10m", ""),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    def _fetch_air_quality(self) -> int | None:
        params = {
            "latitude": self._settings.weather_latitude,
            "longitude": self._settings.weather_longitude,
            "current": "us_aqi",
            "timezone": self._settings.weather_timezone,
        }
        try:
            response = self._session.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params=params,
                timeout=self._settings.http_timeout_seconds,
            )
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            return None
        payload = response.json()
        current = payload.get("current", {})
        value = current.get("us_aqi")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _format_local_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    hour = dt.strftime("%I").lstrip("0") or "0"
    return f"{hour}:{dt.strftime('%M %p')}"


def _aqi_label(value: int | None) -> str:
    if value is None:
        return "Unknown"
    if value <= 50:
        return "Good"
    if value <= 100:
        return "Moderate"
    if value <= 150:
        return "Unhealthy for Sensitive Groups"
    if value <= 200:
        return "Unhealthy"
    if value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _moon_phase(now_utc: datetime) -> dict[str, str]:
    known_new_moon = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    synodic_month_days = 29.53058867
    days_since = (now_utc - known_new_moon).total_seconds() / 86400
    phase = (days_since / synodic_month_days) % 1

    if phase < 0.03 or phase >= 0.97:
        return {"name": "New Moon", "icon": "🌑"}
    if phase < 0.22:
        return {"name": "Waxing Crescent", "icon": "🌒"}
    if phase < 0.28:
        return {"name": "First Quarter", "icon": "🌓"}
    if phase < 0.47:
        return {"name": "Waxing Gibbous", "icon": "🌔"}
    if phase < 0.53:
        return {"name": "Full Moon", "icon": "🌕"}
    if phase < 0.72:
        return {"name": "Waning Gibbous", "icon": "🌖"}
    if phase < 0.78:
        return {"name": "Last Quarter", "icon": "🌗"}
    return {"name": "Waning Crescent", "icon": "🌘"}
