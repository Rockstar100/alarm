from datetime import datetime

import pytest

from alarm.time_utils import ParseError, parse_alarm_time

FIXED_NOW = datetime(2026, 3, 15, 10, 30, 0)


def test_absolute_later_today():
    result = parse_alarm_time("14:05", now=FIXED_NOW)
    assert result == datetime(2026, 3, 15, 14, 5, 0)


def test_absolute_past_rolls_to_tomorrow():
    result = parse_alarm_time("09:00", now=FIXED_NOW)
    assert result == datetime(2026, 3, 16, 9, 0, 0)


def test_absolute_exact_now_rolls_to_tomorrow():
    result = parse_alarm_time("10:30", now=FIXED_NOW)
    assert result == datetime(2026, 3, 16, 10, 30, 0)


def test_absolute_single_digit_hour():
    result = parse_alarm_time("7:05", now=FIXED_NOW)
    assert result == datetime(2026, 3, 16, 7, 5, 0)


def test_absolute_strips_whitespace():
    result = parse_alarm_time("  14:05  ", now=FIXED_NOW)
    assert result == datetime(2026, 3, 15, 14, 5, 0)


def test_absolute_midnight_from_evening_rolls():
    now = datetime(2026, 3, 15, 23, 30, 0)
    result = parse_alarm_time("00:00", now=now)
    assert result == datetime(2026, 3, 16, 0, 0, 0)


def test_absolute_near_midnight_same_day():
    now = datetime(2026, 3, 15, 23, 0, 0)
    result = parse_alarm_time("23:30", now=now)
    assert result == datetime(2026, 3, 15, 23, 30, 0)


def test_relative_minutes():
    result = parse_alarm_time("+15m", now=FIXED_NOW)
    assert result == datetime(2026, 3, 15, 10, 45, 0)


def test_relative_hours():
    result = parse_alarm_time("+2h", now=FIXED_NOW)
    assert result == datetime(2026, 3, 15, 12, 30, 0)


def test_relative_zero_minutes_is_now():
    result = parse_alarm_time("+0m", now=FIXED_NOW)
    assert result == FIXED_NOW


def test_relative_zero_hours_is_now():
    result = parse_alarm_time("+0h", now=FIXED_NOW)
    assert result == FIXED_NOW


def test_relative_case_insensitive():
    result = parse_alarm_time("+10M", now=FIXED_NOW)
    assert result == datetime(2026, 3, 15, 10, 40, 0)


def test_relative_crosses_midnight():
    now = datetime(2026, 3, 15, 23, 30, 0)
    result = parse_alarm_time("+90m", now=now)
    assert result == datetime(2026, 3, 16, 1, 0, 0)


@pytest.mark.parametrize(
    "bad",
    ["", "25:00", "10:60", "noon", "10", "+5", "+5x", "abc", "-5m", "24:00", "1:5"],
)
def test_invalid_times_raise(bad: str):
    with pytest.raises(ParseError):
        parse_alarm_time(bad, now=FIXED_NOW)
