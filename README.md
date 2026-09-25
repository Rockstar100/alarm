# CLI Alarm Clock

A small, deliberate Python CLI alarm clock built as a senior-engineer take-home exercise. The goal is not feature volume — it is clear problem framing, testable core logic, and a demoable product in a short build window.

## What it does

- **Set** alarms with absolute (`HH:MM`) or relative (`+15m`, `+2h`) times
- **List** / **cancel** active alarms
- **Ring** with a console banner + beep until you dismiss or snooze
- **Snooze** — ring prompt `[s]` snoozes the ringing alarm; REPL `snooze <id>` reschedules any known id (including pending-to-ring)
- Interactive **REPL** so the process stays alive and can fire alarms

```text
$ python -m alarm
Alarm clock ready. Type 'help' for commands.
alarm> set +1m Tea
Set [1] 2026-03-15 10:31  Tea  (active)
alarm> list
[1] 2026-03-15 10:31  Tea  (active)
alarm> set 07:30 Wake up
Set [2] 2026-03-16 07:30  Wake up  (active)
alarm> cancel 2
Cancelled [2] 2026-03-16 07:30  Wake up  (done)
```

When an alarm fires:

```text
================================================
  ALARM [1]  10:31  —  Tea
  [d] dismiss    [s] snooze (5 min)
================================================
[d/s]>
```

You can also pass an initial command: `python -m alarm set +30m Standup`.

## Non-goals (deliberate)

| Left out | Why |
|---|---|
| Web UI / React | Spec: CLI only |
| Database | Spec: no DB; persistence is not the interesting problem |
| Recurring alarms / cron | Complexity without proving scheduling correctness |
| OS-level scheduling | Less portable; harder to demo in a screen recording |
| File persistence across restarts | Stretch only; process ownership is enough for the exercise |

## Design decisions

1. **One long-lived process + background poll thread**  
   The REPL owns the session. A daemon thread ticks every ~0.5s and **enqueues** due alarms. The main thread drains the queue and rings — so stdin is never shared across threads (a real race if `input()` ran on the scheduler thread).

2. **Injected clock**  
   `AlarmScheduler` takes a `clock: Callable[[], datetime]`. Production uses `datetime.now`; tests advance a `FakeClock`. This is how “fires at T” is validated without sleeping for minutes.

3. **Parse once, store `datetime`**  
   Relative times resolve at set-time. Absolute `HH:MM` that is already past today rolls to **tomorrow**. That rule is explicit and covered by tests.

4. **Stdlib runtime, pytest for tests**  
   Reviewers can run with stock Python. `winsound.Beep` on Windows; ASCII BEL / print fallback elsewhere.

5. **Ring marks alarm inactive before the handler runs**  
   Prevents re-fire while the user is still at the dismiss/snooze prompt. Snooze reactivates the same id.

6. **Wakeable REPL input**  
   The prompt waits for Enter, but checks a wake flag so a due alarm can interrupt immediately and ring — without reprinting `alarm>` on a timer.

```text
CLI / REPL ──► AlarmScheduler ──► in-memory store
                    │                 │
                    │                 └── pending queue ──► main-thread ring
                    └── time_utils (HH:MM, +Nm/+Nh)
```

## Setup

Requires Python 3.10+. From the repository root (no install needed):

```bash
python -m alarm
pytest
```

`pytest` picks up `pythonpath = ["."]` from `pyproject.toml`.

## Usage

| Command | Example |
|---|---|
| `set <time> [label]` | `set 07:30 Wake up` / `set +10m Tea` |
| `list` | `list` |
| `cancel <id>` | `cancel 1` (also drops a pending-to-ring alarm) |
| `snooze <id> [minutes]` | `snooze 1 5` (REPL reschedule; ring `[s]` snoozes the ringing alarm) |
| `help` | `help` |
| `quit` | `quit` |

Tip for demos: at the `alarm>` prompt type exactly `set +0m Now` (not a shell command, not a comment).

## Tests

```bash
python -m pytest -q
```

Coverage focus:

- Time parsing (absolute roll-forward, relative units, invalid input)
- Scheduler set/list/cancel/snooze/`tick` with a fake clock (no wall-clock sleeps)
- Pending-queue cancel/snooze (no ring after drop)
- Relative time resolved once; IDs not reused after cancel

## Known limits

- Alarms live only while the process is running (no disk persistence).
- One ringing alarm at a time blocks the REPL until dismiss/snooze.
- Beep quality depends on the terminal / OS sound stack.
- No timezone awareness — uses the local system clock.
- Piped / non-TTY stdin blocks on each line and will not wake mid-read when an alarm becomes due (use an interactive terminal for demos).

## Project layout

```text
.
├── README.md
├── pyproject.toml
├── .gitignore
├── alarm/
│   ├── __init__.py
│   ├── __main__.py      # python -m alarm
│   ├── cli.py           # REPL, argparse, banner, beep
│   ├── scheduler.py     # Alarm + AlarmScheduler
│   └── time_utils.py    # HH:MM / +Nm / +Nh → datetime
└── tests/
    ├── test_time_utils.py
    └── test_scheduler.py
```
