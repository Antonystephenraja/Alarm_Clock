"""Launcher: `python alarm.py <command>` is the same as `python -m alarm_clock <command>`."""

import sys

from alarm_clock.cli import main

if __name__ == "__main__":
    sys.exit(main())
