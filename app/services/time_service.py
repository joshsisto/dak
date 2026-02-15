from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings


class TimeService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(self) -> dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(ZoneInfo(self._settings.display_timezone))
        ntp = self._ntp_state()

        return {
            "server_epoch_ms": int(now_utc.timestamp() * 1000),
            "server_time_iso": now_local.isoformat(),
            "timezone": self._settings.display_timezone,
            "ntp_synchronized": ntp["ntp_synchronized"],
            "system_clock_synchronized": ntp["system_clock_synchronized"],
        }

    def _ntp_state(self) -> dict[str, bool | None]:
        ntp_synced = self._read_timedatectl_property("NTPSynchronized")
        clock_synced = self._read_timedatectl_property("SystemClockSynchronized")
        return {
            "ntp_synchronized": ntp_synced,
            "system_clock_synchronized": clock_synced,
        }

    def _read_timedatectl_property(self, name: str) -> bool | None:
        try:
            result = subprocess.run(
                ["timedatectl", "show", "--property", name, "--value"],
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            )
        except Exception:  # noqa: BLE001
            return None

        value = result.stdout.strip().lower()
        if value in {"yes", "true", "1"}:
            return True
        if value in {"no", "false", "0"}:
            return False
        return None
