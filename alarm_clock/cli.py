"""Command-line interface: argument parsing and one handler per command."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from . import __version__, alert, scheduler
from . import timeutil as tu
from .store import Alarm, AlarmError, Store

PROG = "python -m alarm_clock"

EPILOG = """\
examples:
  add 07:30 --daily -m "Wake up"       add 7:30pm 8:15pm      add --in 10s
  list                                 edit 1 --time 06:45    disable 1
  config --format 12 --tz UTC+05:30    run                    (keep it open: it rings the alarms)
"""


# --------------------------------------------------------------------- argument types

def hour_format(value: str) -> str:
    cleaned = value.strip().lower().rstrip("h")
    if cleaned not in ("12", "24"):
        raise argparse.ArgumentTypeError("use 12 or 24")
    return cleaned


def snooze_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number of minutes") from None
    if not 1 <= minutes <= 180:
        raise argparse.ArgumentTypeError("snooze must be between 1 and 180 minutes")
    return minutes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Command-line alarm clock: multiple alarms, daily/one-time, snooze, "
        "timezones and text-based tones.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--data-file",
        metavar="PATH",
        help="where alarms are saved (default: alarms.json next to the package, or $ALARM_CLOCK_DATA)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def command(name, handler, help_, aliases=()):
        p = sub.add_parser(name, aliases=list(aliases), help=help_, description=help_)
        p.set_defaults(handler=handler)
        return p

    fmt_help = "show times as 12-hour or 24-hour (default: your saved setting)"

    p = command("time", cmd_time, "show the current time")
    p.add_argument("--tz", help="timezone to show (default: your saved setting)")
    p.add_argument("--format", type=hour_format, metavar="{12,24}", help=fmt_help)

    p = command("date", cmd_date, "show the current date")
    p.add_argument("--tz", help="timezone to show (default: your saved setting)")

    p = command("add", cmd_add, "set one or more alarms", aliases=["set"])
    p.add_argument("times", nargs="*", metavar="TIME", help="HH:MM, HH:MM:SS or h:MM am/pm; give several to set several")
    p.add_argument("--in", dest="durations", nargs="+", metavar="DURATION", help="ring after a duration instead, e.g. 90s 25m 1h30m (one-time)")
    repeat = p.add_mutually_exclusive_group()
    repeat.add_argument("--daily", dest="repeat", action="store_const", const="daily", help="ring every day")
    repeat.add_argument("--once", dest="repeat", action="store_const", const="once", help="ring once, then switch off (default)")
    p.add_argument("-m", "--message", help='alert message shown when it rings (default: "Alarm!")')
    p.add_argument("-t", "--tone", help="preset name or pattern of '.' '-' and spaces (default: classic)")
    p.add_argument("--tz", help="timezone the alarm time is in (default: your saved setting)")
    p.add_argument("--snooze", type=snooze_minutes, metavar="MIN", help="snooze length for this alarm")

    p = command("list", cmd_list, "list all alarms", aliases=["ls"])
    p.add_argument("--format", type=hour_format, metavar="{12,24}", help=fmt_help)

    p = command("delete", cmd_delete, "delete / cancel alarms", aliases=["cancel", "remove", "rm"])
    p.add_argument("ids", nargs="*", type=int, metavar="ID")
    p.add_argument("--all", action="store_true", help="delete every alarm")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation with --all")

    for name, handler, text in (
        ("enable", cmd_enable, "switch alarms on"),
        ("disable", cmd_disable, "switch alarms off (they stay in the list)"),
    ):
        p = command(name, handler, text)
        p.add_argument("ids", nargs="*", type=int, metavar="ID")
        p.add_argument("--all", action="store_true", help="apply to every alarm")

    p = command("edit", cmd_edit, "change an existing alarm")
    p.add_argument("id", type=int, metavar="ID")
    p.add_argument("--time", dest="at", metavar="TIME", help="new time")
    p.add_argument("-m", "--message", help="new alert message")
    p.add_argument("-t", "--tone", help="new tone")
    p.add_argument("--tz", help="new timezone")
    repeat = p.add_mutually_exclusive_group()
    repeat.add_argument("--daily", dest="repeat", action="store_const", const="daily", help="make it a daily alarm")
    repeat.add_argument("--once", dest="repeat", action="store_const", const="once", help="make it a one-time alarm")
    p.add_argument("--snooze", type=snooze_minutes, metavar="MIN", help="new snooze length")

    p = command("snooze", cmd_snooze, "ring an alarm again in N minutes (same as pressing S while it rings)")
    p.add_argument("id", type=int, metavar="ID")
    p.add_argument("minutes", nargs="?", type=snooze_minutes, help="default: the alarm's / saved snooze length")

    p = command("config", cmd_config, "show or change saved settings")
    p.add_argument("--format", type=hour_format, metavar="{12,24}", help="default clock format")
    p.add_argument("--tz", help="default timezone for new alarms and the clock")
    p.add_argument("--snooze", type=snooze_minutes, metavar="MIN", help="default snooze length")

    p = command("timezones", cmd_timezones, "search the available timezones")
    p.add_argument("filter", nargs="?", help="text to search for, e.g. asia")

    p = command("tone", cmd_tone, "list the preset tones, or preview one")
    p.add_argument("name", nargs="?", help="preset name or pattern to play once")
    p.add_argument("--mute", action="store_true", help="show the tone as text without sound")

    p = command("run", cmd_run, "watch the alarms and ring them (keep this running)")
    p.add_argument("--max-ring", type=int, default=0, metavar="SECONDS", help="auto-stop a ringing alarm after this long (default: ring until dismissed)")
    p.add_argument("--exit-after-ring", action="store_true", help="exit after the first alarm has rung")
    p.add_argument("--mute", action="store_true", help="no sound, text only")
    p.add_argument("--quiet", action="store_true", help="no live 'next alarm' line")
    return parser


# ------------------------------------------------------------------------- helpers

@dataclass
class Context:
    args: argparse.Namespace
    store: Store

    def fmt(self) -> str:
        return getattr(self.args, "format", None) or self.store.settings["time_format"]

    def muted(self) -> bool:
        return bool(getattr(self.args, "mute", False) or os.environ.get("ALARM_CLOCK_MUTE"))


def _next_text(alarm: Alarm, now: datetime, fmt: str) -> str:
    due = alarm.due_at()
    if due is None:
        return "-"
    stamp = tu.format_stamp(tu.in_zone(due, alarm.tz), fmt)
    if alarm.tz != tu.LOCAL:
        stamp += f" {alarm.tz}"  # make it clear this is not your local clock
    if due <= now:
        return f"{stamp} (overdue - is 'run' active?)"
    return f"{stamp} (in {tu.humanize_delta(due - now)})"


def _zone_label(tz: str, moment: datetime) -> str:
    offset = tu.format_offset(moment)
    return tz if tz.startswith("UTC") else f"{tz}, {offset}"


def _ids(args: argparse.Namespace, store: Store, verb: str):
    """Resolve the ID / --all arguments of delete, enable and disable to alarms."""
    if args.all == bool(args.ids):
        raise AlarmError(f"{verb}: give one or more alarm ids, or --all")
    if args.all:
        return list(store.alarms)
    return [store.get(i) for i in dict.fromkeys(args.ids)]  # validates every id before any change


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


class StatusLine:
    """A single line rewritten in place on a terminal."""

    def __init__(self, stream):
        self.stream = stream
        self.shown = False

    def _width(self) -> int:
        return max(20, shutil.get_terminal_size((80, 24)).columns - 1)

    def show(self, text: str) -> None:
        self.stream.write("\r" + text[: self._width()].ljust(self._width()))
        self.stream.flush()
        self.shown = True

    def clear(self) -> None:
        if self.shown:
            self.stream.write("\r" + " " * self._width() + "\r")
            self.stream.flush()
            self.shown = False


# ------------------------------------------------------------------------- handlers

def cmd_time(ctx: Context) -> int:
    tz = tu.normalize_tz(ctx.args.tz or ctx.store.settings["timezone"])
    now = tu.in_zone(tu.utc_now(), tz)
    print(f"Current time: {tu.format_clock(now, ctx.fmt())}   [{_zone_label(tz, now)}]")
    return 0


def cmd_date(ctx: Context) -> int:
    tz = tu.normalize_tz(ctx.args.tz or ctx.store.settings["timezone"])
    now = tu.in_zone(tu.utc_now(), tz)
    print(f"Current date: {tu.format_date(now)}   [{_zone_label(tz, now)}]")
    return 0


def cmd_add(ctx: Context) -> int:
    a, store = ctx.args, ctx.store
    if bool(a.times) == bool(a.durations):
        raise AlarmError("give one or more times (e.g. 07:30) or --in DURATION - one of them, not both")
    repeat = a.repeat or "once"
    if a.durations and repeat == "daily":
        raise AlarmError("--in alarms are one-time; use a clock time for --daily")
    tz = tu.normalize_tz(a.tz or store.settings["timezone"])
    tone = alert.validate_tone(a.tone or "classic")
    message = (a.message or "").strip() or "Alarm!"
    now = tu.utc_now()

    plan = []  # validate everything first so a bad value adds nothing
    for text in a.times:
        at = tu.parse_time_of_day(text)
        plan.append((at, tu.next_occurrence(at, tz, now)))
    for text in a.durations or []:
        target = now + tu.parse_duration(text)
        plan.append((tu.in_zone(target, tz).time().replace(microsecond=0), target))

    fmt = ctx.fmt()
    for at, fire in plan:
        alarm = store.add(
            at=at.isoformat(), tz=tz, repeat=repeat, message=message, tone=tone,
            snooze_minutes=a.snooze, enabled=True, next_fire=tu.to_iso(fire),
        )
        print(f'Added alarm #{alarm.id}: {tu.format_alarm_time(at, fmt)} {repeat} [{tz}] "{message}" (tone: {tone})')
        print(f"  Rings next: {_next_text(alarm, now, fmt)}")
    store.save()
    print(f"Start watching with:  {PROG} run")
    return 0


def cmd_list(ctx: Context) -> int:
    store, fmt = ctx.store, ctx.fmt()
    if not store.alarms:
        print(f"No alarms set. Add one with:  {PROG} add 07:30")
        return 0
    now = tu.utc_now()
    print(f"{'ID':>3}  {'TIME':<12} {'REPEAT':<6}  {'STATUS':<8}  NEXT RING")
    for alarm in sorted(store.alarms, key=lambda a: a.id):
        print(
            f"{alarm.id:>3}  {tu.format_alarm_time(alarm.tod(), fmt):<12} {alarm.repeat:<6}  "
            f"{alarm.status:<8}  {_next_text(alarm, now, fmt)}"
        )
        minutes = alarm.snooze_minutes or store.settings["snooze_minutes"]
        print(f'       tz: {alarm.tz} | tone: {alarm.tone} | snooze: {minutes} min | "{alarm.message}"')
    active = sum(1 for a in store.alarms if a.due_at() is not None)
    print(f"{len(store.alarms)} alarm(s), {active} active.")
    return 0


def cmd_delete(ctx: Context) -> int:
    a, store = ctx.args, ctx.store
    targets = _ids(a, store, "delete")
    if a.all:
        if not targets:
            print("No alarms to delete.")
            return 0
        if not a.yes and not _confirm(f"Delete all {len(targets)} alarm(s)?"):
            print("Cancelled - nothing deleted.")
            return 0
    for alarm in targets:
        store.remove(alarm.id)
    store.save()
    print("Deleted alarm(s): " + ", ".join(f"#{t.id}" for t in targets))
    return 0


def cmd_enable(ctx: Context) -> int:
    store, now, fmt = ctx.store, tu.utc_now(), ctx.fmt()
    for alarm in _ids(ctx.args, store, "enable"):
        if alarm.enabled and alarm.next_fire:
            print(f"Alarm #{alarm.id} is already on.")
            continue
        scheduler.arm(alarm, now)
        print(f"Enabled alarm #{alarm.id}. Rings next: {_next_text(alarm, now, fmt)}")
    store.save()
    return 0


def cmd_disable(ctx: Context) -> int:
    store = ctx.store
    for alarm in _ids(ctx.args, store, "disable"):
        scheduler.disarm(alarm)
        print(f"Disabled alarm #{alarm.id}. Re-enable with: {PROG} enable {alarm.id}")
    store.save()
    return 0


def cmd_edit(ctx: Context) -> int:
    a, store, fmt = ctx.args, ctx.store, ctx.fmt()
    if all(v is None for v in (a.at, a.message, a.tone, a.tz, a.repeat, a.snooze)):
        raise AlarmError("nothing to change - pass at least one of --time, --message, --tone, --tz, --daily/--once, --snooze")
    alarm = store.get(a.id)
    # Validate everything before touching the alarm.
    at = tu.parse_time_of_day(a.at) if a.at is not None else None
    tz = tu.normalize_tz(a.tz) if a.tz is not None else None
    tone = alert.validate_tone(a.tone) if a.tone is not None else None

    reschedule = False
    if at is not None:
        alarm.at, reschedule = at.isoformat(), True
    if tz is not None:
        alarm.tz, reschedule = tz, True
    if a.repeat is not None:
        alarm.repeat, reschedule = a.repeat, True
    if a.message is not None:
        alarm.message = a.message.strip() or "Alarm!"
    if tone is not None:
        alarm.tone = tone
    if a.snooze is not None:
        alarm.snooze_minutes = a.snooze
    now = tu.utc_now()
    if reschedule and alarm.enabled:
        scheduler.arm(alarm, now)
    elif reschedule:
        alarm.snooze_until = None
    store.save()
    print(f'Updated alarm #{alarm.id}: {tu.format_alarm_time(alarm.tod(), fmt)} {alarm.repeat} [{alarm.tz}] "{alarm.message}" (tone: {alarm.tone})')
    if alarm.enabled:
        print(f"  Rings next: {_next_text(alarm, now, fmt)}")
    else:
        print(f"  It is off. Switch it on with: {PROG} enable {alarm.id}")
    return 0


def cmd_snooze(ctx: Context) -> int:
    a, store = ctx.args, ctx.store
    alarm = store.get(a.id)
    minutes = a.minutes or alarm.snooze_minutes or int(store.settings["snooze_minutes"])
    now = tu.utc_now()
    alarm.snooze_until = tu.to_iso(now + timedelta(minutes=minutes))
    store.save()
    print(f"Alarm #{alarm.id} will ring again in {minutes} minute(s). Rings next: {_next_text(alarm, now, ctx.fmt())}")
    print(f"(Keep '{PROG} run' open - it does the ringing.)")
    return 0


def cmd_config(ctx: Context) -> int:
    a, settings = ctx.args, ctx.store.settings
    changed = False
    if a.format:
        settings["time_format"], changed = a.format, True
    if a.tz:
        settings["timezone"], changed = tu.normalize_tz(a.tz), True
    if a.snooze:
        settings["snooze_minutes"], changed = a.snooze, True
    if changed:
        ctx.store.save()
        print("Settings updated.")
    print(f"  clock format : {settings['time_format']}-hour")
    print(f"  timezone     : {settings['timezone']}")
    print(f"  snooze       : {settings['snooze_minutes']} minute(s)")
    print(f"  data file    : {ctx.store.path}")
    return 0


def cmd_timezones(ctx: Context) -> int:
    print("Always available: local, UTC, and offsets such as UTC+05:30 or -8")
    names = tu.tz_names()
    if not names:
        print("Named zones (Asia/Kolkata, Europe/London, ...) are not installed on this machine.")
        print("On Windows run:  pip install tzdata")
        return 0
    needle = (ctx.args.filter or "").lower()
    matches = [n for n in names if needle in n.lower()]
    if not matches:
        print(f"No timezone matches '{ctx.args.filter}'.")
    elif not needle:
        print(f"{len(matches)} named zones installed. Search with, e.g.:  {PROG} timezones asia")
    else:
        print("\n".join(matches))
    return 0


def cmd_tone(ctx: Context) -> int:
    name = ctx.args.name
    if name is None:
        print("Preset tones:")
        for preset, pattern in alert.PRESETS.items():
            print(f"  {preset:<8} {pattern:<14} {alert.tone_text(pattern)}")
        print('Custom: a pattern of "." (short beep), "-" (long beep) and spaces (pause), e.g. ".. -- .."')
        print(f"Preview one with:  {PROG} tone sos")
        return 0
    tone = alert.validate_tone(name)
    pattern = alert.tone_pattern(tone)
    print(f"Tone '{tone}': {alert.tone_text(pattern)}")
    alert.play_once(pattern, alert.Beeper(mute=ctx.muted()))
    return 0


def cmd_run(ctx: Context) -> int:
    a, store = ctx.args, ctx.store
    beeper, keys = alert.Beeper(mute=ctx.muted()), alert.KeyReader()
    line = StatusLine(sys.stdout)
    live = sys.stdout.isatty() and not a.quiet

    def ring(alarm: Alarm, minutes: int) -> bool:
        line.clear()
        when = tu.format_alarm_time(alarm.tod(), store.settings["time_format"])
        title = f"ALARM #{alarm.id}  -  {when}  [{alarm.tz}]"
        return alert.ring(
            title, alarm.message, alarm.tone, minutes, beeper=beeper, keys=keys, max_ring=a.max_ring
        )

    def notify(text: str) -> None:
        line.clear()
        print(text)

    def status(soonest: Optional[Alarm], now: datetime) -> None:
        active = sum(1 for x in store.alarms if x.due_at() is not None)
        if soonest is None:
            line.show("No active alarms - add one from another terminal.   [Ctrl+C to stop]")
            return
        due = soonest.due_at()
        stamp = tu.format_stamp(tu.in_zone(due, soonest.tz), store.settings["time_format"])
        line.show(f"Next: #{soonest.id} at {stamp} - in {tu.format_countdown(due - now)}   ({active} active)   [Ctrl+C to stop]")

    active = sum(1 for x in store.alarms if x.due_at() is not None)
    print(f"Data file: {store.path}")
    print(f"Watching {active} active alarm(s). Ctrl+C stops. While ringing: S = snooze, D / Enter = dismiss.")
    try:
        rings = scheduler.watch(
            store, ring, notify=notify, status=status if live else None,
            max_rings=1 if a.exit_after_ring else 0,
        )
    except KeyboardInterrupt:
        line.clear()
        print("Stopped. Your alarms are saved.")
        return 130
    line.clear()
    print(f"Done - {rings} alarm(s) rang.")
    return 0


# ----------------------------------------------------------------------------- main

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on characters the console cannot show
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    try:
        return args.handler(Context(args, Store(args.data_file))) or 0
    except (AlarmError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
