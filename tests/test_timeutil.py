import unittest
from datetime import datetime, time, timedelta, timezone

from alarm_clock import timeutil as tu


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class ParseTimeTests(unittest.TestCase):
    def test_valid_24h_and_12h(self):
        cases = {
            "07:30": time(7, 30),
            "7:30": time(7, 30),
            "23:59:59": time(23, 59, 59),
            "7:30pm": time(19, 30),
            "7 PM": time(19, 0),
            "12:00 am": time(0, 0),
            "12:00pm": time(12, 0),
            "11:15 a.m.": time(11, 15),
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(tu.parse_time_of_day(text), expected)

    def test_invalid(self):
        for text in ["", "abc", "7", "25:00", "7:75", "24:00", "13pm", "0am", "0730", "7:30:99"]:
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    tu.parse_time_of_day(text)


class ParseDurationTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(tu.parse_duration("90s"), timedelta(seconds=90))
        self.assertEqual(tu.parse_duration("1h30m"), timedelta(minutes=90))
        self.assertEqual(tu.parse_duration("25M"), timedelta(minutes=25))
        self.assertEqual(tu.parse_duration("2 h"), timedelta(hours=2))

    def test_invalid(self):
        for text in ["", "25", "abc", "0s", "25h", "-5m", "1.5h"]:
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    tu.parse_duration(text)


class TimezoneTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(tu.normalize_tz("LOCAL"), "local")
        self.assertEqual(tu.normalize_tz("utc"), "UTC")
        self.assertEqual(tu.normalize_tz("+5:30"), "UTC+05:30")
        self.assertEqual(tu.normalize_tz("utc-8"), "UTC-08:00")
        self.assertEqual(tu.normalize_tz("UTC+0"), "UTC")
        self.assertEqual(tu.normalize_tz("GMT+0530"), "UTC+05:30")

    def test_invalid(self):
        for text in ["UTC+15", "UTC+05:75", "Mars/Base", ""]:
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    tu.normalize_tz(text)

    @unittest.skipUnless(tu.tz_names(), "no tz database installed")
    def test_named_zone_is_case_insensitive(self):
        self.assertEqual(tu.normalize_tz("asia/kolkata"), "Asia/Kolkata")
        moment = tu.in_zone(utc(2026, 10, 6, 0, 0), "Asia/Kolkata")
        self.assertEqual((moment.hour, moment.minute), (5, 30))


class NextOccurrenceTests(unittest.TestCase):
    def test_later_today_in_zone(self):
        # 01:00 UTC is 06:30 in UTC+05:30, so 07:30 there is 02:00 UTC the same day.
        result = tu.next_occurrence(time(7, 30), "UTC+05:30", utc(2026, 10, 6, 1, 0))
        self.assertEqual(result, utc(2026, 10, 6, 2, 0))

    def test_already_passed_rolls_to_tomorrow(self):
        result = tu.next_occurrence(time(7, 30), "UTC+05:30", utc(2026, 10, 6, 3, 0))
        self.assertEqual(result, utc(2026, 10, 7, 2, 0))

    def test_exactly_now_rolls_to_tomorrow(self):
        result = tu.next_occurrence(time(7, 30), "UTC+05:30", utc(2026, 10, 6, 2, 0))
        self.assertEqual(result, utc(2026, 10, 7, 2, 0))

    def test_zone_date_differs_from_utc_date(self):
        # 22:00 UTC is already 03:30 *tomorrow* in UTC+05:30; 07:30 there is 02:00 UTC next day.
        result = tu.next_occurrence(time(7, 30), "UTC+05:30", utc(2026, 10, 6, 22, 0))
        self.assertEqual(result, utc(2026, 10, 7, 2, 0))

    def test_local_zone_hits_the_wall_clock_time(self):
        now = tu.utc_now()
        result = tu.next_occurrence(time(7, 30), "local", now)
        self.assertGreater(result, now)
        self.assertLessEqual(result - now, timedelta(hours=25))
        local = tu.in_zone(result, "local")
        self.assertEqual((local.hour, local.minute), (7, 30))


class FormatTests(unittest.TestCase):
    def test_clock_formats(self):
        moment = datetime(2026, 10, 6, 19, 5, 9)
        self.assertEqual(tu.format_clock(moment, "24"), "19:05:09")
        self.assertEqual(tu.format_clock(moment, "12"), "7:05:09 PM")
        self.assertEqual(tu.format_clock(datetime(2026, 1, 1, 0, 0, 0), "12", seconds=False), "12:00 AM")
        self.assertEqual(tu.format_clock(datetime(2026, 1, 1, 12, 0, 0), "12", seconds=False), "12:00 PM")

    def test_alarm_time_hides_zero_seconds(self):
        self.assertEqual(tu.format_alarm_time(time(7, 30), "24"), "07:30")
        self.assertEqual(tu.format_alarm_time(time(7, 30, 15), "24"), "07:30:15")

    def test_deltas(self):
        self.assertEqual(tu.humanize_delta(timedelta(seconds=12)), "12s")
        self.assertEqual(tu.humanize_delta(timedelta(minutes=5, seconds=3)), "5m 03s")
        self.assertEqual(tu.humanize_delta(timedelta(hours=2, minutes=5)), "2h 05m")
        self.assertEqual(tu.humanize_delta(timedelta(days=1, hours=2, minutes=5)), "1d 2h 05m")
        self.assertEqual(tu.format_countdown(timedelta(minutes=24, seconds=13)), "00:24:13")
        self.assertEqual(tu.format_countdown(timedelta(days=1, hours=2, minutes=3, seconds=4)), "1d 02:03:04")


if __name__ == "__main__":
    unittest.main()
