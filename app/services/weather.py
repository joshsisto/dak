from __future__ import annotations

from datetime import datetime
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
            "current": "temperature_2m,apparent_temperature,is_day,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
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

        units = payload.get("current_units", {})
        return {
            "current": current_block,
            "daily": daily_list,
            "temperature_unit": units.get("temperature_2m", "°"),
            "wind_speed_unit": units.get("wind_speed_10m", ""),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
