from __future__ import annotations

import re
from datetime import datetime, timedelta

_ABSOLUTE = re.compile(r"^(\d{1,2}):(\d{2})$")
_RELATIVE = re.compile(r"^\+(\d+)([mh])$", re.IGNORECASE)


class ParseError(ValueError):
    pass


def parse_alarm_time(text: str, *, now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now()

    text = text.strip()
    if not text:
        raise ParseError("empty time string")

    abs_match = _ABSOLUTE.match(text)
    if abs_match:
        hour = int(abs_match.group(1))
        minute = int(abs_match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ParseError(f"invalid clock time: {text!r}")
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)  # already passed today
        return candidate

    rel_match = _RELATIVE.match(text)
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if amount == 0:
            return now  # +0m / +0h, next tick
        delta = timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)
        return now + delta

    raise ParseError(
        f"unrecognized time {text!r}; use HH:MM (e.g. 07:30) or +Nm/+Nh (e.g. +15m)"
    )
