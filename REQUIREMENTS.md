# Alarm Clock CLI — Requirements (v0.1 draft)

> **Scope update (v1.0 build):** the feature list grew to multiple alarms, list/edit/delete, enable/disable,
> daily alarms, snooze, timezones, 12/24h format and text tones. Those need state between commands, so alarms
> are now saved in one small JSON file (still no database). Sections 2, 5 and 10 below describe the original
> single-alarm scope; see [README.md](README.md) for what was actually built.

Status: draft for review. Items marked **[DECIDE]** are open questions; each has a recommended default so work can start without waiting.

---

## 1. Goal

A small Python command-line tool that waits until a given time (or for a given duration) and then alerts the user in the terminal until they dismiss it.

**Design principles**
- One job, done well: set an alarm, wait, ring.
- Standard library only. No third-party dependencies, nothing to `pip install`.
- Predictable and scriptable: clear output, meaningful exit codes.

## 2. Non-goals (explicitly out of scope for v1)

- No GUI / TUI / system-tray (CLI text output only).
- No database. No config files. Nothing written to disk in v1.
- No background daemon or OS service — the alarm lives only as long as the process runs.
- No network, accounts, or sync.
- No recurring alarms, no multiple named alarms, no calendar integration.
- No desktop notifications or custom sound files (see §10 for future ideas).

## 3. Target environment

| Item | Decision |
|---|---|
| Language | Python 3.12 (what is installed); avoid features newer than 3.10 so it stays portable |
| OS | Windows 11 primary; should not crash on Linux/macOS (degraded sound is fine) |
| Dependencies | stdlib only |
| Run mode | Foreground process in a terminal; terminal must stay open |

## 4. Usage scenarios

1. "Wake me at 07:30" → `alarm 07:30`
2. "Tell me in 25 minutes" (pomodoro / tea timer) → `alarm --in 25m`
3. "Remind me to call the bank at 15:00" → `alarm 15:00 --label "Call the bank"`
4. "Changed my mind" → press Ctrl+C while waiting; exits cleanly.

(Command name/entry point is illustrative; see §6.)

## 5. Functional requirements

Priority: **MUST** = v1 ships with it, **SHOULD** = v1 if cheap, **COULD** = later.

### 5.1 Setting the alarm

| ID | Priority | Requirement |
|---|---|---|
| F1 | MUST | Accept an absolute time of day in 24-hour `HH:MM` format (e.g. `07:30`, `18:05`). |
| F2 | MUST | Accept a relative duration via `--in` (e.g. `90s`, `25m`, `2h`, `1h30m`). |
| F3 | MUST | Exactly one of F1 / F2 must be given; giving both or neither is a usage error. |
| F4 | SHOULD | Accept 12-hour input with am/pm (`7:30am`, `7:30 pm`). |
| F5 | SHOULD | Accept an optional `--label TEXT` shown when the alarm rings. |
| F6 | COULD | Accept seconds in absolute time (`HH:MM:SS`). |

### 5.2 Resolving the target time

| ID | Priority | Requirement |
|---|---|---|
| F7 | MUST | If an absolute time has already passed today, schedule it for **tomorrow** (**[DECIDE]** — alternative: reject with an error; recommended: roll to tomorrow). |
| F8 | MUST | On start, print the resolved target as a full local date+time and the time remaining, e.g. `Alarm set for Tue 2026-10-07 07:30 (in 14h 02m)`. This makes the roll-to-tomorrow behavior visible, not surprising. |
| F9 | MUST | Reject zero or negative durations, and durations above a sane cap (suggest 24h) with a clear message. |
| F10 | MUST | Reject invalid times (`25:00`, `7:75`, `abc`) with a clear message showing the expected format. |

### 5.3 Waiting

| ID | Priority | Requirement |
|---|---|---|
| F11 | MUST | Wait in the foreground without busy-looping (negligible CPU use). |
| F12 | MUST | Trigger within ~1 second of the target time. |
| F13 | MUST | Remain correct if the machine sleeps/hibernates mid-wait: compare against the wall clock on each tick rather than trusting one long sleep, so a resume past the target rings immediately. |
| F14 | SHOULD | Show a single-line live countdown that updates in place (`Time left: 00:24:13`), and a `--quiet` flag to suppress it. |
| F15 | MUST | Ctrl+C while waiting cancels the alarm, prints `Alarm cancelled.`, and exits with code 130 (no traceback). |

### 5.4 Ringing

| ID | Priority | Requirement |
|---|---|---|
| F16 | MUST | When the time is reached, print a clear, visible message including the label (if any) and the actual time it fired. |
| F17 | MUST | Produce an audible alert using stdlib only: `winsound.Beep` on Windows; fall back to the terminal bell character elsewhere or if `winsound` is unavailable. |
| F18 | MUST | Repeat the alert (with a short pause) until the user dismisses it — it must not beep once and exit. |
| F19 | MUST | Ctrl+C while ringing dismisses the alarm cleanly and exits with code 0 (no traceback). |
| F20 | SHOULD | Optional auto-stop: `--max-ring SECONDS` (default: ring until dismissed). |
| F21 | COULD | Snooze: a key press during ringing re-arms for N minutes. Needs non-blocking key input, which differs per OS — deliberately deferred. |

### 5.5 CLI behavior

| ID | Priority | Requirement |
|---|---|---|
| F22 | MUST | `-h/--help` shows usage with examples. |
| F23 | SHOULD | `--version` prints the version. |
| F24 | MUST | Errors go to stderr; normal output to stdout. |
| F25 | SHOULD | A `--dry-run` flag that prints the resolved target time and exits (useful for testing the parser without waiting). |

## 6. CLI surface (sketch, not final)

```
alarm HH:MM              [--label TEXT] [--quiet] [--max-ring SECONDS]
alarm --in DURATION      [--label TEXT] [--quiet] [--max-ring SECONDS]
alarm --dry-run ...
alarm -h | --version
```

Invocation form (**[DECIDE]**): `python alarm.py 07:30` is simplest; a `python -m alarm_clock` package form is the better home for a multi-file structure. Recommended: package with `python -m alarm_clock`, since you are planning a file structure anyway.

Duration grammar: one or more `<number><unit>` groups, units `h`, `m`, `s`, case-insensitive, optional whitespace-free concatenation (`1h30m`, `45s`). Bare numbers (`--in 25`) are rejected as ambiguous (**[DECIDE]** — alternative: treat a bare number as minutes).

## 7. Exit codes

| Code | Meaning |
|---|---|
| 0 | Alarm fired and was dismissed (or auto-stopped), or `--dry-run`/help/version succeeded |
| 2 | Usage or validation error (bad time, bad duration, conflicting args) |
| 130 | Cancelled with Ctrl+C before the alarm fired |

## 8. Non-functional requirements

- **Accuracy:** fires within 1 s of target (tick interval ≤ 1 s).
- **Resource use:** idle CPU effectively 0%; no memory growth over a 24 h wait.
- **Robustness:** no tracebacks for any user-triggerable error or Ctrl+C.
- **Testability:** time parsing and target-time resolution must be separable from waiting/ringing so they can be unit-tested with an injected "now" and without real sleeping or sound. This is the single most important structural requirement.
- **Readability:** type hints, short functions, docstrings on public functions.
- **Terminal output:** plain ASCII only (Windows consoles with legacy code pages can choke on fancy characters); no color dependence.

## 9. Edge cases to decide up front

| Case | Proposed behavior |
|---|---|
| `00:00`, `23:59` | Valid |
| `24:00` | Invalid |
| Exact current minute (e.g. 14:05 typed at 14:05:30) | Treated as passed → tomorrow (target is 14:05:00, already behind us) |
| Time exactly equal to now | Fires immediately |
| DST change between now and target | Use local wall-clock time; document that a target inside a skipped/repeated hour may be off by an hour. Acceptable for v1. |
| System clock changed while waiting | Wall-clock comparison means it follows the new clock; acceptable and documented |
| Terminal closed / laptop shut down | Alarm is lost — by design (no persistence). Stated in `--help`. |
| Non-interactive stdout (piped) | No in-place countdown; plain lines only |
| Label with quotes/Unicode | Passed through; if the console can't encode it, replace rather than crash |
| Very long label | Printed as-is; no truncation |

## 10. Future ideas (not v1)

- Multiple alarms in one run (`alarm 07:30 08:00`)
- Weekday/recurring schedules
- Snooze (F21)
- Persist alarms to a JSON file (still not a database), plus a separate `list`/`cancel` command and background runner
- Custom sound file; desktop toast notifications
- 12h/24h display preference

## 11. Acceptance criteria (v1 done when)

1. `alarm --in 5s` prints the resolved time, waits ~5 s, rings repeatedly, and Ctrl+C stops it with exit code 0.
2. `alarm HH:MM` for a time 1–2 minutes ahead fires within 1 s of that minute boundary.
3. `alarm HH:MM` for a time earlier than now reports tomorrow's date in the confirmation line.
4. `alarm 25:00`, `alarm --in abc`, `alarm 07:30 --in 5m`, and `alarm` (no args) each print a clear error to stderr and exit 2, with no traceback.
5. Ctrl+C during the wait prints `Alarm cancelled.` and exits 130.
6. `--dry-run` never sleeps and never makes a sound.
7. Parsing/resolving logic has unit tests covering the cases in §9, runnable with `python -m unittest` and no sound or delay.
8. Runs on a clean Python 3.12 install with no `pip install`.

## 12. Open questions (with recommended answers)

| # | Question | Recommended |
|---|---|---|
| 1 | Time already passed today: roll to tomorrow, or error? | Roll to tomorrow, and print the full date so it is obvious |
| 2 | Bare number for `--in`: minutes, or reject? | Reject; require a unit |
| 3 | 12-hour am/pm input in v1? | Yes if it is a small parser addition; otherwise defer |
| 4 | Snooze in v1? | No — defer; it forces OS-specific key handling |
| 5 | Run as a module (`python -m alarm_clock`) or a single script? | Module, to match the multi-file plan |
| 6 | Should "no database" also rule out a tiny JSON state file later? | Treat JSON persistence as a separate future feature (§10), not v1 |
| 7 | Is a live countdown wanted, or just a quiet wait? | Live countdown on by default, `--quiet` to disable |
| 8 | Ring forever, or auto-stop after a limit? | Ring until dismissed; `--max-ring` is optional |

## 13. Suggested responsibility split (to feed your file-structure planning)

Not a prescription — just the seams the requirements imply:

- **Input parsing** — turn `HH:MM`, am/pm, and duration strings into values; raise a typed validation error. Pure, no I/O.
- **Target resolution** — given "now" + parsed input, return the target datetime (roll-over logic lives here). Pure, takes `now` as a parameter.
- **Waiting loop** — tick against the wall clock, drive the countdown display; clock and sleep are injectable so tests don't wait.
- **Alerting** — beep/print loop with the Windows/fallback sound choice isolated in one place.
- **CLI entry** — argument parsing, wiring, exit codes, top-level Ctrl+C handling.
- **Tests** — cover parsing and resolution heavily; wait/alert tested with fakes.

## 14. Suggested next steps

1. Review §12 and confirm or change the recommended answers.
2. Lock v1 scope: F-items marked MUST, plus whichever SHOULDs you want.
3. Draft the file structure from §13.
4. Implement parsing and resolution first (testable without time), then the wait loop, then alerting, then CLI wiring.
