import unittest

from alarm_clock import alert


class FakeBeeper:
    def __init__(self):
        self.beeps = []

    def beep(self, hz, ms):
        self.beeps.append((hz, ms))


class FakeKeys:
    """Scripted key presses: '' means 'no key this poll'."""

    active = True

    def __init__(self, script):
        self.script = list(script)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def poll(self):
        return (self.script.pop(0) or None) if self.script else None

    def drain(self):
        pass


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run_ring(keys, **kw):
    clock, beeper, lines = FakeTime(), FakeBeeper(), []
    result = alert.ring(
        "ALARM #1", "Wake up!", kw.pop("tone", "classic"), 5,
        beeper=beeper, keys=keys, out=lines.append,
        monotonic=clock.monotonic, sleep=clock.sleep, **kw,
    )
    return result, beeper, lines


class ToneTests(unittest.TestCase):
    def test_presets_and_custom_patterns(self):
        self.assertEqual(alert.validate_tone("SOS"), "sos")
        self.assertEqual(alert.validate_tone(" .. -- .. "), ".. -- ..")
        self.assertEqual(alert.validate_tone(".__."), ".--.")  # '_' is an alias for '-'

    def test_invalid_patterns(self):
        for text in ["", "   ", "beep", ".x.", "   "]:
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    alert.validate_tone(text)

    def test_text_rendering(self):
        self.assertEqual(alert.tone_text(". ."), "beep, beep")
        self.assertEqual(alert.tone_text("..- -"), "beep beep BEEEP, BEEEP")


class RingTests(unittest.TestCase):
    def test_snooze_key_returns_true(self):
        result, beeper, lines = run_ring(FakeKeys(["", "", "s"]))
        self.assertTrue(result)
        self.assertIn("Snoozed for 5 minute(s).", lines)

    def test_dismiss_keys_return_false(self):
        for key in ["d", "D", "\r", " ", "q"]:
            with self.subTest(key):
                result, _, lines = run_ring(FakeKeys(["", key]))
                self.assertFalse(result)
                self.assertIn("Dismissed.", lines)

    def test_unrecognised_keys_are_ignored(self):
        result, _, _ = run_ring(FakeKeys(["x", "z", "d"]))
        self.assertFalse(result)

    def test_plays_the_tone_pattern(self):
        _, beeper, _ = run_ring(FakeKeys(["d"] * 1), tone=".-")
        # 'd' is polled before the first symbol, so nothing has played yet
        self.assertEqual(beeper.beeps, [])
        _, beeper, _ = run_ring(FakeKeys([""] * 6 + ["d"]), tone=".-")
        self.assertEqual(beeper.beeps[:2], [(alert.SHORT_HZ, alert.SHORT_MS), (alert.LONG_HZ, alert.LONG_MS)])

    def test_ctrl_c_dismisses(self):
        class Interrupting(FakeKeys):
            def poll(self):
                raise KeyboardInterrupt

        result, _, lines = run_ring(Interrupting([]))
        self.assertFalse(result)
        self.assertIn("Dismissed.", lines)

    def test_max_ring_auto_stops(self):
        result, _, lines = run_ring(FakeKeys([]), max_ring=5)
        self.assertFalse(result)
        self.assertTrue(any(line.startswith("Auto-stopped after 5s") for line in lines))


if __name__ == "__main__":
    unittest.main()
