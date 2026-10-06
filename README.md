# Alarm Clock CLI

A command-line alarm clock. Python standard library only, no UI, no database.
Alarms are saved in one small JSON file (`alarms.json`, created next to the package on first use).

## How it works

Two parts, usually in two terminals:

1. **Manage alarms** with commands (`add`, `list`, `edit`, `delete`, ...). They just edit `alarms.json`.
2. **Ring them** with `run`. Leave it open; it watches the clock and rings alarms when they are due.
   It notices changes made from the other terminal within a second.

Alarms only ring while `run` is open. If an alarm came due more than 5 minutes before `run` started, it is
skipped (and a daily alarm moves to tomorrow).

```powershell
cd D:\Task\alarm_clock
python alarm.py <command>            # the file to run
python -m alarm_clock <command>      # exactly the same thing
```

Only `alarm.py` is meant to be run. The files inside `alarm_clock/` are modules; running one of them directly
(e.g. `python alarm_clock\cli.py`) fails with "attempted relative import".

## Command table

| # | Feature | Command to paste |
|---|---------|------------------|
| 1 | Show current time | `python -m alarm_clock time` |
| 2 | Show current date | `python -m alarm_clock date` |
| 3 | Set alarm (one-time) | `python -m alarm_clock add 07:30` |
| 4 | Set multiple alarms | `python -m alarm_clock add 07:30 12:00 18:45` |
| 5 | List alarms | `python -m alarm_clock list` |
| 6 | Delete / cancel alarm | `python -m alarm_clock delete 1` (several: `delete 1 2 3`; all: `delete --all`) |
| 7 | Enable alarm | `python -m alarm_clock enable 1` |
| 8 | Disable alarm | `python -m alarm_clock disable 1` |
| 9 | Edit alarm | `python -m alarm_clock edit 1 --time 06:45 --message "Gym time"` |
| 10 | One-time alarm | `python -m alarm_clock add 07:30 --once` (the default) |
| 11 | Daily alarm | `python -m alarm_clock add 07:30 --daily` |
| 12 | Custom alert message | `python -m alarm_clock add 07:30 --message "Take medicine"` |
| 13 | Custom text-based tone | `python -m alarm_clock add 07:30 --tone ".. -- .."` (or a preset: `--tone sos`) |
| 14 | Preview / list tones | `python -m alarm_clock tone` then `python -m alarm_clock tone sos` |
| 15 | 12 / 24-hour format | `python -m alarm_clock config --format 12` (or `--format 24`; one-off: `time --format 12`) |
| 16 | Timezone selection | `python -m alarm_clock config --tz UTC+05:30` (one alarm: `add 07:30 --tz UTC-08:00`) |
| 17 | Search timezones | `python -m alarm_clock timezones` |
| 18 | Snooze | While ringing press **S**. Or from the CLI: `python -m alarm_clock snooze 1 10` |
| 19 | Set alarm in N seconds/minutes | `python -m alarm_clock add --in 30s` (also `5m`, `1h30m`) |
| 20 | Start ringing alarms | `python -m alarm_clock run` |

Aliases: `set` = `add`, `ls` = `list`, `cancel` / `remove` / `rm` = `delete`.

While an alarm rings: **S** snooze, **D** / Enter / Space dismiss, **Ctrl+C** also dismisses.
Ctrl+C when nothing is ringing stops `run`.

## Times

- 24-hour: `07:30`, `19:45`, `23:59:30`
- 12-hour: `7:30am`, `7:30 pm`, `7pm`
- A time that already passed today rings tomorrow (the confirmation line shows the date).

## Tones

A tone is a preset (`classic`, `urgent`, `gentle`, `sos`) or your own pattern:
`.` short beep, `-` long beep, space = pause. Example: `".. -- .."`.
The tone is also shown as text while ringing (`beep beep, BEEEP BEEEP, ...`).
(A pattern that starts with `-` needs the `=` form: `--tone="-.-"`.)

## Timezones

`local` (default), `UTC`, and fixed offsets (`UTC+05:30`, `-8`) always work.
Named zones such as `Asia/Kolkata` need the tz database, which Windows Python does not ship:
`pip install tzdata` (then `timezones asia` lists them).
Offsets do not follow daylight-saving changes; named zones and `local` do.

## Other options

| Option | Purpose |
|--------|---------|
| `--data-file PATH` (before the command) | use a different alarms file |
| `ALARM_CLOCK_DATA` env var | same, set once |
| `run --max-ring 60` | auto-stop a ringing alarm after 60 s |
| `run --mute` / `ALARM_CLOCK_MUTE=1` | show everything, make no sound |
| `run --exit-after-ring` | exit after the first alarm rings |
| `config --snooze 10` | default snooze length (per alarm: `add ... --snooze 3`) |

## Quick test (about 30 seconds)

```powershell
python -m alarm_clock add --in 15s --message "It works" --tone ".. --"
python -m alarm_clock run
```
After ~15 s it rings. Press **S** to snooze or **D** to dismiss.

## Project layout

```
alarm.py        <- run this (launcher)
alarm_clock/
  __main__.py   entry point used by `python -m alarm_clock`
  timeutil.py   parsing, timezones, formatting, next-occurrence math (pure)
  store.py      Alarm model + JSON persistence
  alert.py      tones, beeper, key reading, the ringing loop
  scheduler.py  due/advance/missed logic and the watch loop
  cli.py        argparse commands
tests/          python -m unittest discover -s tests -t .
```
