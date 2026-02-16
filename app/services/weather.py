from __future__ import annotations

from io import BytesIO
import math
from datetime import datetime, timezone
from pathlib import Path
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

SYNODIC_MONTH_DAYS = 29.53058867


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
        self._moon_data_cache: dict[str, Any] = {}
        self._moon_data_cached_hour: str | None = None
        self._settings.moon_cache_directory.mkdir(parents=True, exist_ok=True)

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
        now_utc = datetime.now(timezone.utc)
        moon = _moon_phase(now_utc)
        moon_data = self._fetch_moon_data(now_utc)
        moon_age = moon_data.get("age_days")
        if moon_age is None:
            moon_age = moon["age_days"]

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
                "moon_illumination": moon["illumination_percent"],
                "moon_cycle_direction": moon["cycle_direction"],
                "moon_cycle_progress": moon["cycle_progress_percent"],
                "moon_age_days": round(float(moon_age), 1) if moon_age is not None else None,
                "moon_next_phase": moon["next_major_phase"],
                "moon_days_until_next_phase": moon["days_until_next_phase"],
                "moon_distance_km": moon_data.get("distance_km"),
                "moon_angular_diameter_arcsec": moon_data.get("angular_diameter_arcsec"),
                "moon_phase_angle_deg": moon_data.get("phase_angle_deg"),
                "moon_image_url": moon_data.get("image_url"),
                "moon_image_source": moon_data.get("image_source"),
                "moon_image_key": moon_data.get("image_key"),
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

    def _fetch_moon_data(self, now_utc: datetime) -> dict[str, Any]:
        hour_key = now_utc.strftime("%Y-%m-%dT%H")
        if self._moon_data_cache and self._moon_data_cached_hour == hour_key:
            return self._moon_data_cache

        timestamp = now_utc.strftime("%Y-%m-%dT%H:00")
        try:
            response = self._session.get(
                f"https://svs.gsfc.nasa.gov/api/dialamoon/{timestamp}",
                timeout=self._settings.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            low_res_url = (
                payload.get("image", {}).get("url")
                or payload.get("su_image", {}).get("url")
            )
            high_res_tiff_url = (
                payload.get("image_highres", {}).get("url")
                or payload.get("su_image_highres", {}).get("url")
            )
            image_url = self._resolve_moon_image_url(
                hour_key=hour_key,
                high_res_tiff_url=high_res_tiff_url,
                fallback_url=low_res_url,
            )

            self._moon_data_cache = {
                "age_days": _float_or_none(payload.get("age")),
                "distance_km": _float_or_none(payload.get("distance")),
                "angular_diameter_arcsec": _float_or_none(payload.get("diameter")),
                "phase_angle_deg": _float_or_none(payload.get("phase")),
                "image_url": image_url,
                "image_source": "NASA Dial-a-Moon",
                "image_key": hour_key,
            }
            self._moon_data_cached_hour = hour_key
        except Exception:  # noqa: BLE001
            return self._moon_data_cache

        return self._moon_data_cache

    def _resolve_moon_image_url(
        self,
        *,
        hour_key: str,
        high_res_tiff_url: str | None,
        fallback_url: str | None,
    ) -> str | None:
        if not high_res_tiff_url:
            return fallback_url
        cached_name = _moon_cached_filename(hour_key)
        cached_path = self._settings.moon_cache_directory / cached_name
        if not cached_path.exists():
            self._convert_tiff_to_jpeg(high_res_tiff_url, cached_path)
        if cached_path.exists():
            return f"/moon-cache/{cached_name}"
        return fallback_url

    def _convert_tiff_to_jpeg(self, tiff_url: str, output_path: Path) -> bool:
        try:
            from PIL import Image  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            return False

        try:
            response = self._session.get(
                tiff_url,
                timeout=max(self._settings.http_timeout_seconds, 25),
            )
            response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(BytesIO(response.content)) as image:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                resampling = getattr(Image, "Resampling", Image)
                image.thumbnail((2200, 2200), resampling.LANCZOS)
                image.save(output_path, format="JPEG", quality=92, optimize=True)
            return True
        except Exception:  # noqa: BLE001
            return False


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


def _moon_phase(now_utc: datetime) -> dict[str, str | int | float]:
    known_new_moon = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    days_since = (now_utc - known_new_moon).total_seconds() / 86400
    phase = (days_since / SYNODIC_MONTH_DAYS) % 1
    illumination = int(round(((1 - math.cos(phase * 2 * math.pi)) / 2) * 100))
    cycle_progress_percent = int(round(phase * 100))
    age_days = phase * SYNODIC_MONTH_DAYS
    cycle_direction = "Waxing" if phase < 0.5 else "Waning"
    next_phase_name, days_until_next_phase = _next_major_phase(phase)

    if phase < 0.03 or phase >= 0.97:
        phase_name = "New Moon"
        icon = "🌑"
    elif phase < 0.22:
        phase_name = "Waxing Crescent"
        icon = "🌒"
    elif phase < 0.28:
        phase_name = "First Quarter"
        icon = "🌓"
    elif phase < 0.47:
        phase_name = "Waxing Gibbous"
        icon = "🌔"
    elif phase < 0.53:
        phase_name = "Full Moon"
        icon = "🌕"
    elif phase < 0.72:
        phase_name = "Waning Gibbous"
        icon = "🌖"
    elif phase < 0.78:
        phase_name = "Last Quarter"
        icon = "🌗"
    elif phase < 0.97:
        phase_name = "Waning Crescent"
        icon = "🌘"
    else:
        phase_name = "New Moon"
        icon = "🌑"

    return {
        "name": phase_name,
        "icon": icon,
        "illumination_percent": illumination,
        "cycle_progress_percent": cycle_progress_percent,
        "age_days": age_days,
        "cycle_direction": cycle_direction,
        "next_major_phase": next_phase_name,
        "days_until_next_phase": days_until_next_phase,
    }


def _next_major_phase(phase: float) -> tuple[str, float]:
    phase_markers: list[tuple[float, str]] = [
        (0.25, "First Quarter"),
        (0.50, "Full Moon"),
        (0.75, "Last Quarter"),
        (1.00, "New Moon"),
    ]
    for marker, name in phase_markers:
        if phase < marker:
            return name, round((marker - phase) * SYNODIC_MONTH_DAYS, 1)
    return "New Moon", 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _moon_cached_filename(hour_key: str) -> str:
    normalized = hour_key.replace("-", "").replace(":", "").replace("T", "")
    return f"moon-{normalized}.jpg"
