from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hyperloop.cli.formatters.time import format_relative_time


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TestFormatRelativeTime:
    def test_seconds_ago(self) -> None:
        now = _utc_now()
        ts = now - timedelta(seconds=30)
        assert format_relative_time(ts, now=now) == "30s ago"

    def test_minutes_ago(self) -> None:
        now = _utc_now()
        ts = now - timedelta(minutes=5)
        assert format_relative_time(ts, now=now) == "5m ago"

    def test_hours_ago(self) -> None:
        now = _utc_now()
        ts = now - timedelta(hours=2)
        assert format_relative_time(ts, now=now) == "2h ago"

    def test_days_ago(self) -> None:
        now = _utc_now()
        ts = now - timedelta(days=3)
        assert format_relative_time(ts, now=now) == "3d ago"

    def test_minutes_rounds_down(self) -> None:
        now = _utc_now()
        ts = now - timedelta(minutes=5, seconds=45)
        assert format_relative_time(ts, now=now) == "5m ago"

    def test_hours_rounds_down(self) -> None:
        now = _utc_now()
        ts = now - timedelta(hours=2, minutes=45)
        assert format_relative_time(ts, now=now) == "2h ago"

    def test_boundary_60_seconds_becomes_1m(self) -> None:
        now = _utc_now()
        ts = now - timedelta(seconds=60)
        assert format_relative_time(ts, now=now) == "1m ago"

    def test_boundary_60_minutes_becomes_1h(self) -> None:
        now = _utc_now()
        ts = now - timedelta(minutes=60)
        assert format_relative_time(ts, now=now) == "1h ago"

    def test_boundary_24_hours_becomes_1d(self) -> None:
        now = _utc_now()
        ts = now - timedelta(hours=24)
        assert format_relative_time(ts, now=now) == "1d ago"

    def test_zero_seconds(self) -> None:
        now = _utc_now()
        assert format_relative_time(now, now=now) == "0s ago"

    def test_large_days(self) -> None:
        now = _utc_now()
        ts = now - timedelta(days=100)
        assert format_relative_time(ts, now=now) == "100d ago"
