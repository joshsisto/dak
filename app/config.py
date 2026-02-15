from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CalendarSource:
    id: str
    name: str
    url: str


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    calendar_ics_url: str
    calendar_sources: tuple[CalendarSource, ...]
    calendar_days_ahead: int
    calendar_event_limit: int
    display_timezone: str
    weather_latitude: float
    weather_longitude: float
    weather_temperature_unit: str
    weather_wind_speed_unit: str
    weather_timezone: str
    photos_source: str
    photos_directory: Path
    photos_limit: int
    icloud_shared_album_url: str
    data_refresh_seconds: int
    slideshow_interval_seconds: int
    http_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        legacy_calendar_url = os.getenv("CALENDAR_ICS_URL", "").strip()
        calendar_sources = _parse_calendar_sources(
            os.getenv("CALENDAR_SOURCES", ""),
            legacy_calendar_url,
        )

        return cls(
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=int(os.getenv("PORT", "8080")),
            calendar_ics_url=legacy_calendar_url,
            calendar_sources=calendar_sources,
            calendar_days_ahead=int(os.getenv("CALENDAR_DAYS_AHEAD", "7")),
            calendar_event_limit=int(os.getenv("CALENDAR_EVENT_LIMIT", "12")),
            display_timezone=os.getenv("DISPLAY_TIMEZONE", os.getenv("TZ", "UTC")).strip(),
            weather_latitude=float(os.getenv("WEATHER_LATITUDE", "40.7128")),
            weather_longitude=float(os.getenv("WEATHER_LONGITUDE", "-74.0060")),
            weather_temperature_unit=os.getenv("WEATHER_TEMPERATURE_UNIT", "fahrenheit").strip(),
            weather_wind_speed_unit=os.getenv("WEATHER_WIND_SPEED_UNIT", "mph").strip(),
            weather_timezone=os.getenv("WEATHER_TIMEZONE", "auto").strip(),
            photos_source=os.getenv("PHOTOS_SOURCE", "directory").strip().lower(),
            photos_directory=Path(os.getenv("PHOTOS_DIRECTORY", "./photos")).expanduser(),
            photos_limit=int(os.getenv("PHOTOS_LIMIT", "50")),
            icloud_shared_album_url=os.getenv("ICLOUD_SHARED_ALBUM_URL", "").strip(),
            data_refresh_seconds=int(os.getenv("DATA_REFRESH_SECONDS", "300")),
            slideshow_interval_seconds=int(os.getenv("SLIDESHOW_INTERVAL_SECONDS", "20")),
            http_timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS", "12")),
        )


def _parse_calendar_sources(raw_sources: str, legacy_calendar_url: str) -> tuple[CalendarSource, ...]:
    """
    Parse CALENDAR_SOURCES entries in format:
    Name|https://example.ics;Other Name|https://example2.ics
    """

    entries: list[tuple[str, str]] = []

    for raw_entry in raw_sources.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "|" in entry:
            name, url = entry.split("|", 1)
            source_name = name.strip()
            source_url = url.strip()
        else:
            source_name = ""
            source_url = entry
        if not source_url:
            continue
        entries.append((source_name, source_url))

    if legacy_calendar_url and legacy_calendar_url not in {url for _, url in entries}:
        entries.append(("Calendar", legacy_calendar_url))

    named_entries = _normalize_calendar_names(entries)
    return tuple(
        CalendarSource(id=f"cal-{index + 1}", name=name, url=url)
        for index, (name, url) in enumerate(named_entries)
    )


def _normalize_calendar_names(entries: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    seen_names: dict[str, int] = {}
    for index, (name, url) in enumerate(entries, start=1):
        base_name = name or f"Calendar {index}"
        count = seen_names.get(base_name, 0) + 1
        seen_names[base_name] = count
        if count > 1:
            normalized_name = f"{base_name} ({count})"
        else:
            normalized_name = base_name
        output.append((normalized_name, url))
    return output
