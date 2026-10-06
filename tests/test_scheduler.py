import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alarm_clock import scheduler
from alarm_clock.store import Store

START = datetime(2026, 10, 6, 7, 29, 50, tzinfo=timezone.utc)


class Stop(Exception):
    """Raised by the fake clock to end a watch loop that would otherwise run forever."""


class FakeClock:
    def __init__(self, start, limit=timedelta(days=3)):
        self.now = start
        self.limit = start + limit

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)
        if self.now > self.limit:
            raise Stop()


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "alarms.json")

    def make_alarm(self, at="07:30:00", repeat="once", **kw):
        alarm = self.store.add(at=at, tz="UTC", repeat=repeat, **kw)
        scheduler.arm(alarm, START)
        self.store.save()
        return alarm

    def watch(self, clock, ring, **kw):
        return scheduler.watch(self.store, ring, clock=clock, sleep=clock.sleep, **kw)

    def test_one_time_alarm_rings_on_time_then_switches_off(self):
        alarm = self.make_alarm()
        clock, rang = FakeClock(START), []
        count = self.watch(clock, lambda a, m: rang.append(clock.now) or False, max_rings=1)
        self.assertEqual(count, 1)
        self.assertEqual(rang, [datetime(2026, 10, 6, 7, 30, tzinfo=timezone.utc)])
        self.assertFalse(alarm.enabled)
        self.assertIsNone(alarm.next_fire)

    def test_daily_alarm_moves_to_next_day(self):
        alarm = self.make_alarm(repeat="daily")
        clock = FakeClock(START)
        self.watch(clock, lambda a, m: False, max_rings=1)
        self.assertTrue(alarm.enabled)
        self.assertEqual(alarm.next_fire_dt, datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc))

    def test_daily_alarm_rings_on_consecutive_days(self):
        self.make_alarm(repeat="daily")
        clock, rang = FakeClock(START), []
        self.watch(clock, lambda a, m: rang.append(clock.now) or False, max_rings=3)
        self.assertEqual([r.day for r in rang], [6, 7, 8])

    def test_disabled_alarm_never_rings(self):
        alarm = self.make_alarm()
        scheduler.disarm(alarm)

        def fail(a, m):
            raise AssertionError("a disabled alarm rang")

        with self.assertRaises(Stop):
            self.watch(FakeClock(START, limit=timedelta(hours=2)), fail)

    def test_snooze_rings_again_after_the_snooze_length(self):
        alarm = self.make_alarm()
        clock, rang = FakeClock(START), []
        answers = iter([True, False])  # snooze the first ring, dismiss the second
        self.watch(clock, lambda a, m: rang.append((clock.now, m)) or next(answers), max_rings=2)
        self.assertEqual(rang[0][0], datetime(2026, 10, 6, 7, 30, tzinfo=timezone.utc))
        self.assertEqual(rang[1][0], datetime(2026, 10, 6, 7, 35, tzinfo=timezone.utc))
        self.assertEqual(rang[0][1], 5)  # default snooze length
        self.assertFalse(alarm.enabled)
        self.assertIsNone(alarm.snooze_until)

    def test_alarm_snooze_length_overrides_the_default(self):
        self.make_alarm(snooze_minutes=2)
        clock, rang = FakeClock(START), []
        answers = iter([True, False])
        self.watch(clock, lambda a, m: rang.append(clock.now) or next(answers), max_rings=2)
        self.assertEqual(rang[1] - rang[0], timedelta(minutes=2))

    def test_missed_alarms_are_skipped_only_beyond_the_grace_period(self):
        old = self.make_alarm(at="06:00:00")        # armed for tomorrow by arm(); force it into the past
        old.next_fire = (START - timedelta(hours=1)).isoformat()
        recent = self.make_alarm(at="07:29:00")
        recent.next_fire = (START - timedelta(minutes=1)).isoformat()
        missed = scheduler.reconcile_missed(self.store, START)
        self.assertEqual([a.id for a, _ in missed], [old.id])
        self.assertFalse(old.enabled)
        self.assertTrue(recent.enabled)
        self.assertEqual([a.id for a in scheduler.due_alarms(self.store, START)], [recent.id])

    def test_edits_made_by_another_process_are_picked_up(self):
        alarm = self.make_alarm()
        clock = FakeClock(START, limit=timedelta(hours=1))
        edited = []

        def sleep(seconds):
            if not edited:  # on the first tick another process switches the alarm off
                edited.append(True)
                other = Store(self.store.path)
                scheduler.disarm(other.get(alarm.id))
                other.save()
                stat = self.store.path.stat()  # file times can be coarse; make the change visible
                os.utime(self.store.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
            clock.sleep(seconds)

        with self.assertRaises(Stop):
            scheduler.watch(
                self.store, lambda a, m: self.fail("rang after being disabled elsewhere"),
                clock=clock, sleep=sleep,
            )


if __name__ == "__main__":
    unittest.main()
