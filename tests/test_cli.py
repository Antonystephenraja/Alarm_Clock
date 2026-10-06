import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from alarm_clock.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "alarms.json"

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--data-file", str(self.data), *argv])
        return code, out.getvalue(), err.getvalue()

    def alarms(self):
        return json.loads(self.data.read_text(encoding="utf-8"))["alarms"]

    # ---- clock
    def test_time_and_date(self):
        code, out, _ = self.run_cli("time", "--tz", "UTC+05:30", "--format", "12")
        self.assertEqual(code, 0)
        self.assertIn("Current time:", out)
        self.assertIn("UTC+05:30", out)
        self.assertRegex(out, r"(AM|PM)")
        code, out, _ = self.run_cli("date", "--tz", "UTC")
        self.assertEqual(code, 0)
        self.assertIn("Current date:", out)

    # ---- add / list
    def test_add_one_time_and_list(self):
        code, out, _ = self.run_cli("add", "07:30", "-m", "Wake up")
        self.assertEqual(code, 0)
        self.assertIn("Added alarm #1", out)
        code, out, _ = self.run_cli("list")
        self.assertIn("07:30", out)
        self.assertIn("once", out)
        self.assertIn("Wake up", out)

    def test_add_multiple_alarms_in_one_command(self):
        code, out, _ = self.run_cli("add", "07:30", "8:15pm", "23:00:30")
        self.assertEqual(code, 0)
        self.assertEqual([a["id"] for a in self.alarms()], [1, 2, 3])
        self.assertEqual([a["at"] for a in self.alarms()], ["07:30:00", "20:15:00", "23:00:30"])

    def test_add_daily_with_tone_snooze_and_tz(self):
        code, _, _ = self.run_cli("add", "06:00", "--daily", "-t", ".. -- ..", "--snooze", "9", "--tz", "UTC+05:30")
        self.assertEqual(code, 0)
        alarm = self.alarms()[0]
        self.assertEqual((alarm["repeat"], alarm["tone"], alarm["snooze_minutes"], alarm["tz"]),
                         ("daily", ".. -- ..", 9, "UTC+05:30"))

    def test_add_relative_alarm(self):
        code, out, _ = self.run_cli("add", "--in", "10s", "2m")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.alarms()), 2)
        self.assertIn("in 10s", out)

    def test_invalid_input_adds_nothing_and_exits_2(self):
        cases = [
            ("add", "07:30", "25:00"),
            ("add", "--in", "abc"),
            ("add", "07:30", "--in", "5m"),
            ("add",),
            ("add", "--in", "5m", "--daily"),
            ("add", "07:30", "--tone", "beep"),
            ("add", "07:30", "--tz", "Mars/Base"),
        ]
        for argv in cases:
            with self.subTest(argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn("error:", err)
        self.assertFalse(self.data.exists())

    # ---- enable / disable / delete / edit
    def test_disable_and_enable(self):
        self.run_cli("add", "07:30")
        self.run_cli("disable", "1")
        self.assertFalse(self.alarms()[0]["enabled"])
        _, out, _ = self.run_cli("list")
        self.assertIn("off", out)
        self.run_cli("enable", "1")
        self.assertTrue(self.alarms()[0]["enabled"])
        self.assertIsNotNone(self.alarms()[0]["next_fire"])

    def test_delete_by_id_and_all(self):
        self.run_cli("add", "07:30", "08:30", "09:30")
        code, _, _ = self.run_cli("delete", "2")
        self.assertEqual([a["id"] for a in self.alarms()], [1, 3])
        code, _, err = self.run_cli("cancel", "1", "99")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.alarms()), 2)  # unknown id: nothing deleted
        code, _, _ = self.run_cli("delete", "--all", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.alarms(), [])

    def test_ids_are_never_reused(self):
        self.run_cli("add", "07:30")
        self.run_cli("delete", "1")
        self.run_cli("add", "08:00")
        self.assertEqual(self.alarms()[0]["id"], 2)

    def test_edit(self):
        self.run_cli("add", "07:30")
        before = self.alarms()[0]["next_fire"]
        code, out, _ = self.run_cli("edit", "1", "--time", "9pm", "-m", "Evening", "--daily", "-t", "gentle", "--snooze", "3")
        self.assertEqual(code, 0)
        alarm = self.alarms()[0]
        self.assertEqual((alarm["at"], alarm["message"], alarm["repeat"], alarm["tone"], alarm["snooze_minutes"]),
                         ("21:00:00", "Evening", "daily", "gentle", 3))
        self.assertNotEqual(alarm["next_fire"], before)

    def test_edit_needs_a_change_and_a_valid_id(self):
        self.run_cli("add", "07:30")
        self.assertEqual(self.run_cli("edit", "1")[0], 2)
        self.assertEqual(self.run_cli("edit", "5", "-m", "x")[0], 2)

    def test_edit_of_disabled_alarm_keeps_it_off(self):
        self.run_cli("add", "07:30")
        self.run_cli("disable", "1")
        self.run_cli("edit", "1", "--time", "08:00")
        alarm = self.alarms()[0]
        self.assertEqual((alarm["at"], alarm["enabled"], alarm["next_fire"]), ("08:00:00", False, None))

    # ---- snooze / config / tones
    def test_snooze_command(self):
        self.run_cli("add", "07:30")
        code, _, _ = self.run_cli("snooze", "1", "7")
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.alarms()[0]["snooze_until"])
        _, out, _ = self.run_cli("list")
        self.assertIn("snoozed", out)

    def test_config_changes_the_display_format(self):
        self.run_cli("add", "19:30")
        code, out, _ = self.run_cli("config", "--format", "12", "--tz", "UTC+05:30", "--snooze", "10")
        self.assertEqual(code, 0)
        self.assertIn("12-hour", out)
        _, out, _ = self.run_cli("list")
        self.assertIn("7:30 PM", out)
        self.assertIn("10 min", out)
        _, out, _ = self.run_cli("list", "--format", "24")
        self.assertIn("19:30", out)
        self.run_cli("add", "06:00")
        self.assertEqual(self.alarms()[1]["tz"], "UTC+05:30")  # new alarms use the saved timezone

    def test_tone_list_and_preview(self):
        code, out, _ = self.run_cli("tone")
        self.assertIn("sos", out)
        code, out, _ = self.run_cli("tone", ". .", "--mute")
        self.assertEqual(code, 0)
        self.assertIn("beep, beep", out)
        self.assertEqual(self.run_cli("tone", "nope", "--mute")[0], 2)

    def test_timezones_command(self):
        code, out, _ = self.run_cli("timezones")
        self.assertEqual(code, 0)
        self.assertIn("UTC+05:30", out)

    # ---- misc
    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("COMMAND", out)

    def test_data_file_saved_with_a_bom_still_loads(self):
        self.run_cli("add", "07:30")
        self.data.write_text(self.data.read_text(encoding="utf-8"), encoding="utf-8-sig")
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("07:30", out)

    def test_corrupt_data_file_is_reported_not_overwritten(self):
        self.data.write_text("{not json", encoding="utf-8")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 2)
        self.assertIn("Cannot read", err)
        self.assertEqual(self.data.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
