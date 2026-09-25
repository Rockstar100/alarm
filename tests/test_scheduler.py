from datetime import datetime, timedelta

import pytest

from alarm.scheduler import AlarmScheduler


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def test_set_list_cancel():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)

    a1 = sched.set("10:30", "Coffee")
    a2 = sched.set("+1h", "Standup")
    assert [a.id for a in sched.list()] == [a1.id, a2.id]

    sched.cancel(a1.id)
    assert [a.id for a in sched.list()] == [a2.id]


def test_tick_fires_due_alarms():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    fired: list[int] = []
    sched = AlarmScheduler(clock=clock, on_ring=lambda a: fired.append(a.id))

    early = sched.set("+5m", "soon")
    later = sched.set("+30m", "later")

    clock.advance(minutes=5)
    result = sched.tick()
    assert [a.id for a in result] == [early.id]
    assert fired == [early.id]
    assert early.active is False
    assert later.active is True


def test_tick_does_not_refire_inactive():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    fired: list[int] = []
    sched = AlarmScheduler(clock=clock, on_ring=lambda a: fired.append(a.id))
    sched.set("+0m", "now")

    assert len(sched.tick()) == 1
    assert len(sched.tick()) == 0
    assert fired == [1]


def test_tick_without_on_ring_enqueues_pending():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+0m", "queued")
    result = sched.tick()
    assert [a.id for a in result] == [alarm.id]
    pending = sched.drain_pending()
    assert [a.id for a in pending] == [alarm.id]
    assert sched.drain_pending() == []


def test_multiple_due_fire_in_time_order():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    fired: list[int] = []
    sched = AlarmScheduler(clock=clock, on_ring=lambda a: fired.append(a.id))
    later = sched.set("+10m", "later")
    earlier = sched.set("+5m", "earlier")
    clock.advance(minutes=10)
    result = sched.tick()
    assert [a.id for a in result] == [earlier.id, later.id]
    assert fired == [earlier.id, later.id]


def test_snooze_reactivates_and_reschedules():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+0m", "nap")
    sched.tick()
    assert alarm.active is False

    snoozed = sched.snooze(alarm.id, 5)
    assert snoozed.active is True
    assert snoozed.when == datetime(2026, 3, 15, 10, 5)

    clock.advance(minutes=5)
    fired = sched.tick()
    assert [a.id for a in fired] == [alarm.id]


def test_cancel_unknown_raises():
    sched = AlarmScheduler(clock=FakeClock(datetime(2026, 3, 15, 10, 0)))
    with pytest.raises(KeyError, match="no alarm with id 99"):
        sched.cancel(99)


def test_start_stop_lifecycle():
    sched = AlarmScheduler(
        clock=FakeClock(datetime(2026, 3, 15, 10, 0)),
        poll_interval=0.05,
    )
    sched.start()
    assert sched._thread is not None and sched._thread.is_alive()
    sched.stop()
    assert sched._thread is None


def test_cancel_inactive_raises():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+0m")
    sched.cancel(alarm.id)
    with pytest.raises(ValueError, match="already inactive"):
        sched.cancel(alarm.id)


def test_cancel_pending_prevents_ring():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+0m", "soon")
    sched.tick()
    assert sched.has_pending()
    cancelled = sched.cancel(alarm.id)
    assert cancelled.active is False
    assert sched.drain_pending() == []
    assert not sched.has_pending()


def test_snooze_pending_skips_ring_and_reschedules():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+0m", "soon")
    sched.tick()
    assert sched.has_pending()
    snoozed = sched.snooze(alarm.id, 5)
    assert snoozed.active is True
    assert snoozed.when == datetime(2026, 3, 15, 10, 5)
    assert sched.drain_pending() == []


def test_relative_when_resolved_once():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+10m", "Tea")
    when = alarm.when
    clock.advance(minutes=3)
    assert alarm.when == when == datetime(2026, 3, 15, 10, 10)


def test_ids_not_reused_after_cancel():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    first = sched.set("+5m")
    sched.cancel(first.id)
    second = sched.set("+5m")
    assert second.id == first.id + 1


def test_snooze_negative_raises():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock)
    alarm = sched.set("+10m")
    with pytest.raises(ValueError):
        sched.snooze(alarm.id, -1)


def test_snooze_zero_makes_immediately_due():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    sched = AlarmScheduler(clock=clock, on_ring=lambda _a: None)
    alarm = sched.set("+30m")
    sched.snooze(alarm.id, 0)
    assert alarm.when == clock.now
    assert [a.id for a in sched.tick()] == [alarm.id]


def test_cancel_during_due_prevents_fire():
    clock = FakeClock(datetime(2026, 3, 15, 10, 0))
    fired: list[int] = []
    sched = AlarmScheduler(clock=clock, on_ring=lambda a: fired.append(a.id))
    alarm = sched.set("+0m")
    sched.cancel(alarm.id)
    assert sched.tick() == []
    assert fired == []
