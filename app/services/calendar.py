from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar

from app.config import CalendarSource, Settings

logger = logging.getLogger(__name__)


class CalendarService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._settings.calendar_cache_directory.mkdir(parents=True, exist_ok=True)
        self._settings.calendar_events_text_file.parent.mkdir(parents=True, exist_ok=True)

    def upcoming_events(self) -> dict[str, Any]:
        tz = ZoneInfo(self._settings.display_timezone)
        now = datetime.now(tz)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month_start = self._next_month_start(month_start)

        if not self._settings.calendar_sources:
            result = {
                "combined": [],
                "by_calendar": [],
                "errors": [],
                "month_view": self._build_month_view(
                    month_start,
                    next_month_start,
                    {},
                    now.date(),
                ),
            }
            self._write_events_report(result)
            return result

        event_window_end = now + timedelta(days=self._settings.calendar_days_ahead)
        query_start = min(now - timedelta(hours=12), month_start)
        query_end = max(event_window_end, next_month_start)

        combined: list[dict[str, Any]] = []
        by_calendar: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        month_event_map: dict[date, list[dict[str, Any]]] = {}

        for source in self._settings.calendar_sources:
            try:
                source_events = self._events_from_source(source, tz, query_start, query_end)
            except Exception as exc:  # noqa: BLE001
                errors.append({"calendar_name": source.name, "message": str(exc)})
                by_calendar.append({"id": source.id, "name": source.name, "events": []})
                continue

            for event in source_events:
                self._attach_event_to_month(
                    month_event_map,
                    event,
                    month_start.date(),
                    next_month_start.date(),
                )

            upcoming = [event for event in source_events if event["end"] >= now]
            upcoming.sort(key=lambda e: (e["start"], e["all_day"], e["title"]))
            combined.extend(upcoming)
            by_calendar.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "events": [
                        self._serialize_event(event)
                        for event in upcoming[: self._settings.calendar_event_limit]
                    ],
                }
            )

        combined.sort(key=lambda e: (e["start"], e["all_day"], e["title"]))
        combined = combined[: self._settings.calendar_event_limit]

        result = {
            "combined": [self._serialize_event(event) for event in combined],
            "by_calendar": by_calendar,
            "errors": errors,
            "month_view": self._build_month_view(
                month_start,
                next_month_start,
                month_event_map,
                now.date(),
            ),
        }
        self._write_events_report(result)
        return result

    def _events_from_source(
        self,
        source: CalendarSource,
        tz: ZoneInfo,
        range_start: datetime,
        range_end: datetime,
    ) -> list[dict[str, Any]]:
        ics_text = self._get_cached_or_live_ics(source)
        calendar = Calendar.from_ical(ics_text)
        expanded = recurring_ical_events.of(calendar).between(range_start, range_end)

        events: list[dict[str, Any]] = []
        for item in expanded:
            parsed = self._parse_event(item, source, tz)
            if not parsed:
                continue
            events.append(parsed)

        events.sort(key=lambda e: (e["start"], e["all_day"], e["title"]))
        return events

    def _parse_event(
        self,
        raw_event: Any,
        source: CalendarSource,
        tz: ZoneInfo,
    ) -> dict[str, Any] | None:
        raw_start = raw_event.get("DTSTART")
        if raw_start is None:
            return None

        start, is_all_day = self._normalize_datetime(raw_start.dt, tz)

        raw_end = raw_event.get("DTEND")
        if raw_end is None:
            end = start + (timedelta(days=1) if is_all_day else timedelta(hours=1))
        else:
            end, _ = self._normalize_datetime(raw_end.dt, tz)

        title = str(raw_event.get("SUMMARY", "(No title)"))
        location = str(raw_event.get("LOCATION", "")).strip()

        return {
            "calendar_id": source.id,
            "calendar_name": source.name,
            "title": title,
            "location": location,
            "start": start,
            "end": end,
            "all_day": is_all_day,
        }

    def _normalize_datetime(self, value: date | datetime, tz: ZoneInfo) -> tuple[datetime, bool]:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=tz)
            return value.astimezone(tz), False
        normalized = datetime.combine(value, time.min, tzinfo=tz)
        return normalized, True

    def _serialize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        start: datetime = event["start"]
        end: datetime = event["end"]
        all_day = event["all_day"]

        if all_day:
            time_label = "All day"
        else:
            hour = start.strftime("%I").lstrip("0") or "0"
            time_label = f"{hour}:{start.strftime('%M %p')}"

        return {
            "calendar_id": event["calendar_id"],
            "calendar_name": event["calendar_name"],
            "title": event["title"],
            "location": event["location"],
            "start_iso": start.isoformat(),
            "end_iso": end.isoformat(),
            "day_label": f"{start.strftime('%a, %b')} {start.day}",
            "time_label": time_label,
            "all_day": all_day,
        }

    def _attach_event_to_month(
        self,
        month_event_map: dict[date, list[dict[str, Any]]],
        event: dict[str, Any],
        month_start_date: date,
        month_end_date_exclusive: date,
    ) -> None:
        start_date = event["start"].date()
        if event["all_day"]:
            end_exclusive = event["end"].date()
        else:
            end_exclusive = event["end"].date() + timedelta(days=1)

        if end_exclusive <= start_date:
            end_exclusive = start_date + timedelta(days=1)

        clipped_start = max(start_date, month_start_date)
        clipped_end = min(end_exclusive, month_end_date_exclusive)
        if clipped_start >= clipped_end:
            return

        serialized = self._serialize_event(event)
        day = clipped_start
        while day < clipped_end:
            month_event_map.setdefault(day, []).append(serialized)
            day += timedelta(days=1)

    def _build_month_view(
        self,
        month_start: datetime,
        next_month_start: datetime,
        month_event_map: dict[date, list[dict[str, Any]]],
        today_date: date,
    ) -> dict[str, Any]:
        for events in month_event_map.values():
            events.sort(key=lambda e: (e["start_iso"], e["all_day"], e["title"]))

        first_weekday_sunday = (month_start.weekday() + 1) % 7
        calendar_grid_start = month_start.date() - timedelta(days=first_weekday_sunday)
        days_in_month = (next_month_start.date() - month_start.date()).days
        total_cells = ((first_weekday_sunday + days_in_month + 6) // 7) * 7

        cells: list[dict[str, Any]] = []
        for offset in range(total_cells):
            cell_date = calendar_grid_start + timedelta(days=offset)
            in_month = month_start.date() <= cell_date < next_month_start.date()
            day_events = month_event_map.get(cell_date, []) if in_month else []
            cells.append(
                {
                    "date": cell_date.isoformat(),
                    "day": cell_date.day,
                    "in_month": in_month,
                    "is_today": cell_date == today_date,
                    "event_count": len(day_events),
                    "events": day_events[:2],
                    "more_count": max(0, len(day_events) - 2),
                }
            )

        return {
            "month_label": month_start.strftime("%B %Y"),
            "weekday_labels": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
            "cells": cells,
        }

    def _next_month_start(self, month_start: datetime) -> datetime:
        if month_start.month == 12:
            return month_start.replace(year=month_start.year + 1, month=1)
        return month_start.replace(month=month_start.month + 1)

    def _get_cached_or_live_ics(self, source: CalendarSource) -> str:
        cache_file = self._cache_file_for_source(source)
        cached = self._read_cache_file(cache_file)
        if cached and self._is_cache_fresh(cached):
            return cached["ics"]

        try:
            response = self._session.get(
                source.url,
                timeout=self._settings.http_timeout_seconds,
            )
            response.raise_for_status()
            ics_text = response.text
            self._write_cache_file(cache_file, source.url, ics_text)
            return ics_text
        except Exception as exc:  # noqa: BLE001
            if cached and cached.get("ics"):
                logger.warning(
                    "Using stale cached ICS for %s because live fetch failed: %s",
                    source.name,
                    exc,
                )
                return cached["ics"]
            raise

    def _cache_file_for_source(self, source: CalendarSource) -> Path:
        return self._settings.calendar_cache_directory / f"{source.id}.json"

    def _read_cache_file(self, cache_file: Path) -> dict[str, str] | None:
        if not cache_file.exists():
            return None
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        fetched_at = payload.get("fetched_at")
        ics_text = payload.get("ics")
        if not isinstance(fetched_at, str) or not isinstance(ics_text, str):
            return None
        return {"fetched_at": fetched_at, "ics": ics_text}

    def _write_cache_file(self, cache_file: Path, source_url: str, ics_text: str) -> None:
        payload = {
            "fetched_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            "source_url": source_url,
            "ics": ics_text,
        }
        cache_file.write_text(json.dumps(payload), encoding="utf-8")

    def _is_cache_fresh(self, cached: dict[str, str]) -> bool:
        fetched_at_raw = cached.get("fetched_at")
        if not fetched_at_raw:
            return False
        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            return False
        if fetched_at.tzinfo is None:
            return False
        age = datetime.now(fetched_at.tzinfo) - fetched_at
        return age.total_seconds() <= self._settings.calendar_cache_seconds

    def _write_events_report(self, payload: dict[str, Any]) -> None:
        now_local = datetime.now()
        lines: list[str] = []
        generated_at = now_local.strftime("%Y-%m-%d %H:%M:%S")
        lines.append("Dashboard Calendar Events")
        lines.append(f"Generated: {generated_at}")
        lines.append(f"Timezone: {self._settings.display_timezone}")
        lines.append("")

        combined = payload.get("combined", [])
        lines.append(f"Combined Upcoming Events ({len(combined)})")
        for event in combined:
            lines.append(self._format_event_line(event))
        if not combined:
            lines.append("- None")
        lines.append("")

        lines.append("By Calendar")
        by_calendar = payload.get("by_calendar", [])
        for calendar in by_calendar:
            name = str(calendar.get("name", "Calendar"))
            events = calendar.get("events", [])
            lines.append(f"[{name}] ({len(events)})")
            if events:
                for event in events:
                    lines.append(self._format_event_line(event))
            else:
                lines.append("- None")
            lines.append("")

        errors = payload.get("errors", [])
        if errors:
            lines.append("Errors")
            for error in errors:
                calendar_name = error.get("calendar_name", "unknown")
                message = error.get("message", "Unknown error")
                lines.append(f"- {calendar_name}: {message}")
            lines.append("")

        text = "\n".join(lines).rstrip() + "\n"
        export_file = self._settings.calendar_events_text_file
        self._write_text_if_changed(export_file, text)

        rotated_file = self._daily_rotated_export_path(export_file, now_local)
        if rotated_file != export_file:
            self._write_text_if_changed(rotated_file, text)

    def _format_event_line(self, event: dict[str, Any]) -> str:
        day = str(event.get("day_label", "")).strip()
        time_label = str(event.get("time_label", "")).strip()
        calendar_name = str(event.get("calendar_name", "")).strip()
        title = str(event.get("title", "(No title)")).strip()
        location = " ".join(str(event.get("location", "")).split()).strip()
        base = f"- {day} {time_label} [{calendar_name}] {title}".strip()
        if location:
            base += f" @ {location}"
        return base

    def _daily_rotated_export_path(self, base_path: Path, now_local: datetime) -> Path:
        date_suffix = now_local.strftime("%Y-%m-%d")
        if base_path.suffix:
            filename = f"{base_path.stem}-{date_suffix}{base_path.suffix}"
        else:
            filename = f"{base_path.name}-{date_suffix}"
        return base_path.with_name(filename)

    def _write_text_if_changed(self, file_path: Path, text: str) -> None:
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            if existing == text:
                return
        file_path.write_text(text, encoding="utf-8")
