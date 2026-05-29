from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import AppConfig


def next_run_at(config: AppConfig, now: datetime | None = None) -> datetime:
    tz = ZoneInfo(config.schedule_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    hour, minute = _parse_schedule_time(config.schedule_time)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


def sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def _parse_schedule_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("SCHEDULE_TIME must use HH:MM.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("SCHEDULE_TIME must use HH:MM in 24-hour time.")
    return hour, minute
