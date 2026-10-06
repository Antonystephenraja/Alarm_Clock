"""Scheduling logic: when alarms are due, how they advance, and the watch loop."""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from . import timeutil as tu
from .store import Alarm, Store

MISSED_GRACE = timedelta(minutes=5)

RingFn = Callable[[Alarm, int], bool]  # (alarm, snooze_minutes) -> True if the user snoozed


def arm(alarm: Alarm, now: datetime) -> None:
    """Switch an alarm on and compute its next ring after `now`."""
    alarm.enabled = True
    alarm.snooze_until = None
    alarm.next_fire = tu.to_iso(tu.next_occurrence(alarm.tod(), alarm.tz, now))


def disarm(alarm: Alarm) -> None:
    """Switch an alarm off and forget any pending ring."""
    alarm.enabled = False
    alarm.next_fire = None
    alarm.snooze_until = None


def due_alarms(store: Store, now: datetime) -> List[Alarm]:
    """Alarms that should ring now, earliest first."""
    due = [a for a in store.alarms if a.due_at() is not None and a.due_at() <= now]
    return sorted(due, key=lambda a: a.due_at())


def upcoming(store: Store) -> Optional[Alarm]:
    """The alarm that will ring soonest, if any."""
    candidates = [a for a in store.alarms if a.due_at() is not None]
    return min(candidates, key=lambda a: a.due_at()) if candidates else None


def advance(alarm: Alarm, now: datetime, record: bool = True) -> None:
    """Move an alarm past a ring: daily alarms jump to their next day, one-time alarms switch off.

    A pending snooze is always cleared. If only the snooze was due, the regular schedule is untouched.
    """
    scheduled_due = (
        alarm.enabled and alarm.next_fire_dt is not None and alarm.next_fire_dt <= now
    )
    alarm.snooze_until = None
    if not scheduled_due:
        return
    if record:
        alarm.last_fired = tu.to_iso(now)
    if alarm.repeat == "daily":
        alarm.next_fire = tu.to_iso(tu.next_occurrence(alarm.tod(), alarm.tz, now))
    else:
        alarm.enabled = False
        alarm.next_fire = None


def reconcile_missed(
    store: Store, now: datetime, grace: timedelta = MISSED_GRACE
) -> List[Tuple[Alarm, datetime]]:
    """Skip alarms that came due more than `grace` ago while nothing was watching."""
    missed = []
    for alarm in store.alarms:
        due = alarm.due_at()
        if due is not None and now - due > grace:
            missed.append((alarm, due))
            advance(alarm, now, record=False)
    return missed


def _ring_one(store: Store, alarm: Alarm, ring: RingFn, clock: Callable[[], datetime]) -> None:
    alarm_id = alarm.id
    minutes = alarm.snooze_minutes or int(store.settings["snooze_minutes"])
    advance(alarm, clock())
    store.save()  # persist the advance first so a crash while ringing cannot re-ring forever
    snoozed = ring(alarm, minutes)
    if snoozed:
        store.load()  # pick up any edits made from another terminal while it was ringing
        current = next((a for a in store.alarms if a.id == alarm_id), None)
        if current is not None:
            current.snooze_until = tu.to_iso(clock() + timedelta(minutes=minutes))
            store.save()


def watch(
    store: Store,
    ring: RingFn,
    *,
    clock: Callable[[], datetime] = tu.utc_now,
    sleep: Callable[[float], None] = _time.sleep,
    notify: Callable[[str], None] = lambda text: None,
    status: Optional[Callable[[Optional[Alarm], datetime], None]] = None,
    max_rings: int = 0,
    tick: float = 1.0,
    grace: timedelta = MISSED_GRACE,
) -> int:
    """Ring alarms as they come due until interrupted (or `max_rings` have rung).

    The wall clock is compared on every tick, so an alarm that came due while the machine
    slept rings as soon as it wakes. Changes made to the data file from another terminal
    are picked up on the next tick. Returns the number of rings.
    """
    fmt = store.settings["time_format"]
    missed = reconcile_missed(store, clock(), grace)
    for alarm, due in missed:
        stamp = tu.format_stamp(tu.in_zone(due, alarm.tz), fmt)
        notify(
            f"Skipped missed alarm #{alarm.id} ({tu.format_alarm_time(alarm.tod(), fmt)}): "
            f"it was due {stamp} while nothing was watching."
        )
    if missed:
        store.save()

    rings = 0
    while True:
        store.reload_if_changed()
        now = clock()
        due = due_alarms(store, now)
        if due:
            _ring_one(store, due[0], ring, clock)
            rings += 1
            if max_rings and rings >= max_rings:
                return rings
            continue
        soonest = upcoming(store)
        if status:
            status(soonest, now)
        wait = tick
        if soonest is not None:
            wait = max(0.05, min(tick, (soonest.due_at() - now).total_seconds()))
        sleep(wait)
