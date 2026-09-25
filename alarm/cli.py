from __future__ import annotations

import argparse
import select
import shlex
import sys
import threading
import time
from typing import Callable, Literal, Sequence

from alarm.scheduler import Alarm, AlarmScheduler

Action = Literal["dismiss", "snooze"]

HELP_TEXT = """\
Commands:
  set <HH:MM|+Nm|+Nh> [label...]   Schedule an alarm
  list                             Show active alarms
  cancel <id>                      Cancel active or pending-to-ring alarm
  snooze <id> [minutes]            Reschedule by id (default 5 min);
                                   also skips a pending ring for that id
  help                             Show this help
  quit / exit                      Stop the scheduler and exit

Tips:
  Past HH:MM rolls to tomorrow. Demo with: set +0m Now
  Ring prompt uses [d] dismiss / [s] snooze — not the alarm> REPL.
"""


def _parse_id(raw: str, *, what: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{what} id must be an integer, got {raw!r}; try list"
        ) from exc
    if value < 1:
        raise ValueError(f"{what} id must be >= 1, got {value}; try list")
    return value


def _beep_once() -> None:
    try:
        import winsound

        winsound.Beep(880, 350)
    except Exception:
        sys.stdout.write("\a")  # no winsound
        sys.stdout.flush()


def _banner(alarm: Alarm) -> str:
    label = alarm.label or "(no label)"
    return (
        "\n"
        + "=" * 48
        + "\n"
        + f"  ALARM [{alarm.id}]  {alarm.when:%H:%M}  —  {label}\n"
        + "  [d] dismiss    [s] snooze (5 min)\n"
        + "=" * 48
        + "\n"
    )


def _ring(
    alarm: Alarm,
    *,
    input_fn: Callable[[str], str] = input,
    beep_fn: Callable[[], None] = _beep_once,
    beep_interval: float = 1.0,
) -> Action:
    stop = threading.Event()

    def _beep_loop() -> None:
        while not stop.is_set():
            try:
                beep_fn()
            except Exception:
                pass
            stop.wait(beep_interval)

    beeper = threading.Thread(target=_beep_loop, name="alarm-beep", daemon=True)
    beeper.start()

    sys.stdout.write(_banner(alarm))
    sys.stdout.flush()

    action: Action = "dismiss"
    try:
        while True:
            try:
                choice = input_fn("[d/s]> ").strip().lower()
            except EOFError:
                action = "dismiss"
                break
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                sys.stdout.flush()
                action = "dismiss"
                break
            if choice in ("d", "dismiss", ""):
                action = "dismiss"
                break
            if choice in ("s", "snooze"):
                action = "snooze"
                break
            sys.stdout.write("  type d to dismiss or s to snooze\n")
            sys.stdout.flush()
    finally:
        stop.set()
        beeper.join(timeout=2.0)

    return action


def _timed_readline(
    prompt: str,
    *,
    timeout: float = 0.5,
    wake: Callable[[], bool] | None = None,
) -> str | None:
    if not sys.stdin.isatty():
        # piped, just wait for a line
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")

    if sys.platform == "win32":
        return _windows_timed_readline(prompt, timeout=timeout, wake=wake)
    return _posix_timed_readline(prompt, timeout=timeout, wake=wake)


def _windows_timed_readline(
    prompt: str,
    *,
    timeout: float,
    wake: Callable[[], bool] | None,
) -> str | None:
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: list[str] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if wake is not None and wake():
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf)
            if ch in ("\x08", "\x7f"):  # backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch == "\x03":  # ctrl-c
                raise KeyboardInterrupt
            if ch == "\x1a":  # ctrl-z
                raise EOFError
            if ch in ("\x00", "\xe0"):  # arrows, extra byte
                if msvcrt.kbhit():
                    msvcrt.getwch()
                continue
            buf.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()
        else:
            time.sleep(0.05)

    return None


def _posix_timed_readline(
    prompt: str,
    *,
    timeout: float,
    wake: Callable[[], bool] | None,
) -> str | None:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: list[str] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if wake is not None and wake():
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        remaining = max(0.0, min(0.1, deadline - time.monotonic()))
        ready, _, _ = select.select([sys.stdin], [], [], remaining)
        if not ready:
            continue
        ch = sys.stdin.read(1)
        if ch == "":
            raise EOFError
        if ch == "\n":
            return "".join(buf)
        if ch in ("\x7f", "\b"):
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch == "\x03":
            raise KeyboardInterrupt
        buf.append(ch)
        sys.stdout.write(ch)
        sys.stdout.flush()

    return None


class AlarmApp:
    def __init__(
        self,
        scheduler: AlarmScheduler | None = None,
        *,
        ring_fn: Callable[..., Action] = _ring,
    ) -> None:
        self.scheduler = scheduler or AlarmScheduler()
        self._ring = ring_fn

    def _handle_ring(self, alarm: Alarm) -> None:
        action = self._ring(alarm)
        if action == "snooze":
            snoozed = self.scheduler.snooze(alarm.id, 5)
            print(f"Snoozed until {snoozed.when:%H:%M}.")
        else:
            print(f"Dismissed alarm [{alarm.id}].")

    def _drain_rings(self) -> None:
        for alarm in self.scheduler.drain_pending():
            self._handle_ring(alarm)

    def run_command(self, argv: Sequence[str]) -> bool:
        if not argv:
            return True

        cmd = argv[0].lower()
        args = list(argv[1:])

        try:
            if cmd in ("quit", "exit", "q"):
                return False
            if cmd in ("help", "h", "?"):
                print(HELP_TEXT)
            elif cmd == "set":
                self._cmd_set(args)
            elif cmd == "list":
                self._cmd_list()
            elif cmd == "cancel":
                self._cmd_cancel(args)
            elif cmd == "snooze":
                self._cmd_snooze(args)
            else:
                print(f"Unknown command: {cmd!r}. Type 'help'.")
        except KeyError as exc:
            # KeyError adds quotes around the text
            print(f"Error: {exc.args[0] if exc.args else exc}")
        except ValueError as exc:
            print(f"Error: {exc}")
        return True

    def _cmd_set(self, args: list[str]) -> None:
        if not args:
            raise ValueError(
                "usage: set <HH:MM|+Nm|+Nh> [label...]  "
                "(examples: set 07:30 Wake up | set +10m Tea)"
            )
        when_text = args[0]
        label = " ".join(args[1:])
        alarm = self.scheduler.set(when_text, label)
        print(f"Set {alarm}")

    def _cmd_list(self) -> None:
        alarms = self.scheduler.list()
        if not alarms:
            print("No active alarms. Use set to schedule one.")
            return
        for alarm in alarms:
            print(alarm)

    def _cmd_cancel(self, args: list[str]) -> None:
        if len(args) != 1:
            raise ValueError("usage: cancel <id>  (see list)")
        alarm_id = _parse_id(args[0], what="cancel")
        alarm = self.scheduler.cancel(alarm_id)
        print(f"Cancelled {alarm}")

    def _cmd_snooze(self, args: list[str]) -> None:
        if not args or len(args) > 2:
            raise ValueError("usage: snooze <id> [minutes]  (see list)")
        alarm_id = _parse_id(args[0], what="snooze")
        if len(args) == 2:
            try:
                minutes = int(args[1])
            except ValueError as exc:
                raise ValueError(
                    f"snooze minutes must be an integer, got {args[1]!r}"
                ) from exc
        else:
            minutes = 5
        alarm = self.scheduler.snooze(alarm_id, minutes)
        print(f"Snoozed {alarm}")

    def repl(self) -> int:
        self.scheduler.start()
        print("Alarm clock ready. Type 'help' for commands.")
        try:
            while True:
                self._drain_rings()
                try:
                    line = _timed_readline(
                        "alarm> ",
                        timeout=0.5,
                        wake=self.scheduler.has_pending,
                    )
                except EOFError:
                    print()
                    break
                except KeyboardInterrupt:
                    print()
                    break

                if line is None:
                    continue

                try:
                    argv = shlex.split(line)
                except ValueError as exc:
                    print(f"Parse error: {exc}")
                    continue
                if not self.run_command(argv):
                    break
        finally:
            self.scheduler.stop()
        print("Goodbye.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm",
        description="CLI alarm clock — set, list, cancel, and snooze alarms.",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Optional initial command (e.g. set +1m Tea). Opens the REPL after.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = AlarmApp()
    if args.command:
        if not app.run_command(args.command):
            return 0
    return app.repl()


if __name__ == "__main__":
    raise SystemExit(main())
