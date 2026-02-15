from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar

from app.config import CalendarSource, Settings


class CalendarService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()

    def upcoming_events(self) -> dict[str, Any]:
        tz = ZoneInfo(self._settings.display_timezone)
        now = datetime.now(tz)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month_start = self._next_month_start(month_start)

        if not self._settings.calendar_sources:
            return {
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

        return {
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

    def _events_from_source(
        self,
        source: CalendarSource,
        tz: ZoneInfo,
        range_start: datetime,
        range_end: datetime,
    ) -> list[dict[str, Any]]:
        response = self._session.get(
            source.url,
            timeout=self._settings.http_timeout_seconds,
        )
        response.raise_for_status()
        calendar = Calendar.from_ical(response.text)
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
