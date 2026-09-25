from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from alarm.time_utils import parse_alarm_time

Clock = Callable[[], datetime]
RingHandler = Callable[["Alarm"], None]


@dataclass
class Alarm:
    id: int
    when: datetime
    label: str = ""
    active: bool = True

    def __str__(self) -> str:
        label = f"  {self.label}" if self.label else ""
        status = "active" if self.active else "done"
        return f"[{self.id}] {self.when:%Y-%m-%d %H:%M}{label}  ({status})"


class AlarmScheduler:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        on_ring: RingHandler | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        self._clock: Clock = clock or datetime.now
        self._on_ring = on_ring
        self._poll_interval = poll_interval
        self._alarms: dict[int, Alarm] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: list[Alarm] = []  # repl drains this

    def set(self, when_text: str, label: str = "") -> Alarm:
        when = parse_alarm_time(when_text, now=self._clock())
        with self._lock:
            alarm = Alarm(id=self._next_id, when=when, label=label)
            self._next_id += 1
            self._alarms[alarm.id] = alarm
            return alarm

    def list(self) -> list[Alarm]:
        with self._lock:
            active = [a for a in self._alarms.values() if a.active]
            return sorted(active, key=lambda a: (a.when, a.id))

    def cancel(self, alarm_id: int) -> Alarm:
        with self._lock:
            alarm = self._require(alarm_id)
            if self._drop_pending_locked(alarm_id):
                alarm.active = False
                return alarm
            if not alarm.active:
                raise ValueError(
                    f"alarm [{alarm_id}] is already inactive; "
                    "use set to create a new one, or snooze to revive it"
                )
            alarm.active = False
            return alarm

    def snooze(self, alarm_id: int, minutes: int = 5) -> Alarm:
        if minutes < 0:
            raise ValueError("snooze minutes must be >= 0 (try snooze <id> 5)")
        with self._lock:
            alarm = self._require(alarm_id)
            self._drop_pending_locked(alarm_id)
            alarm.when = self._clock() + timedelta(minutes=minutes)
            alarm.active = True
            return alarm

    def due(self, now: datetime | None = None) -> list[Alarm]:
        if now is None:
            now = self._clock()
        with self._lock:
            found = [a for a in self._alarms.values() if a.active and a.when <= now]
            return sorted(found, key=lambda a: (a.when, a.id))

    def tick(self) -> list[Alarm]:
        fired: list[Alarm] = []
        for alarm in self.due():
            with self._lock:
                if not alarm.active:
                    continue
                alarm.active = False  # before the handler, or it fires twice
                if self._on_ring is None:
                    self._pending.append(alarm)
                    self._wake.set()
            fired.append(alarm)
            if self._on_ring is not None:
                self._on_ring(alarm)
        return fired

    def drain_pending(self) -> list[Alarm]:
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
            self._wake.clear()
            return items

    def has_pending(self) -> bool:
        return self._wake.is_set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="alarm-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if not self._thread.is_alive():
                self._thread = None

    def _drop_pending_locked(self, alarm_id: int) -> bool:
        before = len(self._pending)
        self._pending = [a for a in self._pending if a.id != alarm_id]
        removed = len(self._pending) < before
        if not self._pending:
            self._wake.clear()
        return removed

    def _require(self, alarm_id: int) -> Alarm:
        try:
            return self._alarms[alarm_id]
        except KeyError as exc:
            raise KeyError(
                f"no alarm with id {alarm_id}; run list to see active alarms"
            ) from exc

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._poll_interval)

    def all_alarms(self) -> Iterable[Alarm]:
        with self._lock:
            return list(self._alarms.values())
