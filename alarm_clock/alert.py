"""The alert side: text-based tones, the beeper, key polling and the ringing loop."""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, Optional

try:
    import msvcrt  # Windows console keys
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

try:
    import winsound  # Windows beeper
except ImportError:  # pragma: no cover - POSIX
    winsound = None

# A tone is a preset name or a pattern: "." short beep, "-" long beep, " " pause.
PRESETS = {
    "classic": ". . . .",
    "urgent": ".-.- .-.-",
    "gentle": "- -",
    "sos": "... --- ...",
}
SHORT_HZ, SHORT_MS = 1000, 150
LONG_HZ, LONG_MS = 800, 450
SYMBOL_GAP = 0.08      # silence between symbols
PAUSE = 0.30           # a space in the pattern
CYCLE_GAP = 1.0        # silence between repeats of the whole pattern
SLICE = 0.05           # how often keys are polled while waiting
MAX_PATTERN = 64

KEY_ACTIONS = {
    "s": "snooze",
    "d": "dismiss", "q": "dismiss", "\r": "dismiss", "\n": "dismiss", " ": "dismiss", "\x1b": "dismiss",
}


# ----------------------------------------------------------------------------- tones

def validate_tone(text: str) -> str:
    """Return a preset name or a cleaned '.-' pattern; raise ValueError otherwise."""
    cleaned = text.strip()
    if cleaned.lower() in PRESETS:
        return cleaned.lower()
    pattern = cleaned.replace("_", "-")
    if (
        not pattern
        or len(pattern) > MAX_PATTERN
        or any(ch not in ".- " for ch in pattern)
        or not any(ch in ".-" for ch in pattern)
    ):
        raise ValueError(
            f"Invalid tone '{text}'. Use a preset ({', '.join(PRESETS)}) or a pattern of "
            "'.' (short beep), '-' (long beep) and spaces (pause), e.g. \".. -- ..\"."
        )
    return pattern


def tone_pattern(tone: str) -> str:
    return PRESETS.get(tone, tone)


def tone_text(pattern: str) -> str:
    """Render a pattern as words: '... ---' -> 'beep beep beep, BEEEP BEEEP BEEEP'."""
    groups = []
    for group in pattern.split():
        groups.append(" ".join("beep" if ch == "." else "BEEEP" for ch in group if ch in ".-"))
    return ", ".join(groups)


# ---------------------------------------------------------------------------- sound

class Beeper:
    """Plays one beep: winsound on Windows, the terminal bell elsewhere. `mute` keeps timing only."""

    def __init__(self, mute: bool = False):
        self.mute = mute
        self._use_winsound = winsound is not None

    def beep(self, hz: int, ms: int) -> None:
        if not self.mute:
            if self._use_winsound:
                try:
                    winsound.Beep(hz, ms)
                    return
                except RuntimeError:
                    self._use_winsound = False  # no usable sound device; fall back to the bell
            sys.stdout.write("\a")
            sys.stdout.flush()
        time.sleep(ms / 1000)


class KeyReader:
    """Non-blocking single-key reader. Inert when stdin is not a terminal."""

    def __init__(self, enabled: bool = True):
        try:
            self.active = bool(enabled and sys.stdin is not None and sys.stdin.isatty())
        except (AttributeError, ValueError):
            self.active = False
        self._saved = None

    def __enter__(self) -> "KeyReader":
        if self.active and msvcrt is None:  # POSIX: unbuffered, no echo
            import termios
            import tty

            fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        return self

    def __exit__(self, *exc) -> None:
        if self._saved is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)
            self._saved = None

    def poll(self) -> Optional[str]:
        if not self.active:
            return None
        if msvcrt is not None:
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):  # arrow/function key: discard its second code
                msvcrt.getwch()
                return None
            return char
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return None
        return os.read(sys.stdin.fileno(), 1).decode("utf-8", "ignore") or None

    def drain(self) -> None:
        """Throw away keys typed before the alarm started ringing."""
        for _ in range(256):
            if self.poll() is None:
                break


_NO_KEYS = KeyReader(enabled=False)


def _poll_action(keys) -> Optional[str]:
    """First recognised key action ('snooze'/'dismiss') waiting in the buffer, else None."""
    while True:
        key = keys.poll()
        if key is None:
            return None
        action = KEY_ACTIONS.get(key.lower())
        if action:
            return action


def _pause(seconds: float, keys, sleep: Callable[[float], None]) -> Optional[str]:
    waited = 0.0
    while waited < seconds:
        action = _poll_action(keys)
        if action:
            return action
        sleep(SLICE)
        waited += SLICE
    return None


def _play(pattern: str, beeper, keys, sleep: Callable[[float], None]) -> Optional[str]:
    """Play the pattern once. Returns a key action if the user interrupted it."""
    for symbol in pattern:
        action = _poll_action(keys)
        if action:
            return action
        if symbol == ".":
            beeper.beep(SHORT_HZ, SHORT_MS)
        elif symbol == "-":
            beeper.beep(LONG_HZ, LONG_MS)
        else:
            action = _pause(PAUSE, keys, sleep)
            if action:
                return action
            continue
        action = _pause(SYMBOL_GAP, keys, sleep)
        if action:
            return action
    return None


def play_once(pattern: str, beeper: Beeper, sleep: Callable[[float], None] = time.sleep) -> None:
    """Preview a tone one time (no key handling)."""
    _play(pattern, beeper, _NO_KEYS, sleep)


# --------------------------------------------------------------------------- ringing

def ring(
    title: str,
    message: str,
    tone: str,
    snooze_minutes: int,
    *,
    beeper,
    keys,
    max_ring: int = 0,
    out: Callable[[str], None] = print,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Ring until dismissed. Returns True if the user chose to snooze, False otherwise.

    Keys: S = snooze, D / Enter / Space / Q / Esc = dismiss. Ctrl+C also dismisses.
    `max_ring` (seconds, 0 = unlimited) stops an unattended alarm automatically.
    """
    pattern = tone_pattern(tone)
    words = tone_text(pattern)
    hint = (
        f"[S] snooze {snooze_minutes} min    [D] or Enter = dismiss    Ctrl+C = dismiss"
        if keys.active
        else "Press Ctrl+C to dismiss"
    )
    bar = "=" * 60
    out(f"\n{bar}\n  {title}\n  {message}\n  {hint}\n{bar}")
    started = monotonic()
    try:
        with keys:
            keys.drain()
            while True:
                out(f"  {words}")
                action = _play(pattern, beeper, keys, sleep) or _pause(CYCLE_GAP, keys, sleep)
                if action == "snooze":
                    out(f"Snoozed for {snooze_minutes} minute(s).")
                    return True
                if action == "dismiss":
                    out("Dismissed.")
                    return False
                if max_ring and monotonic() - started >= max_ring:
                    out(f"Auto-stopped after {max_ring}s (nobody dismissed it).")
                    return False
    except KeyboardInterrupt:
        out("Dismissed.")
        return False
