"""Alarm data model and the small JSON file that persists it (a plain file, not a database)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import List, Optional

ENV_VAR = "ALARM_CLOCK_DATA"
DEFAULT_SETTINGS = {"time_format": "24", "timezone": "local", "snooze_minutes": 5}


class AlarmError(Exception):
    """A problem the user can fix; shown as 'error: ...' without a traceback."""


def default_path() -> Path:
    """$ALARM_CLOCK_DATA if set, otherwise alarms.json next to the package."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "alarms.json"


@dataclass
class Alarm:
    id: int
    at: str                                  # wall-clock time "HH:MM:SS" in `tz`
    tz: str = "local"                        # 'local', 'UTC', 'UTC+05:30' or an IANA name
    repeat: str = "once"                     # 'once' | 'daily'
    message: str = "Alarm!"
    tone: str = "classic"                    # preset name or a '.-' pattern
    snooze_minutes: Optional[int] = None     # None -> use the global setting
    enabled: bool = True
    next_fire: Optional[str] = None          # UTC ISO timestamp of the next scheduled ring
    snooze_until: Optional[str] = None       # UTC ISO timestamp of a pending snooze ring
    last_fired: Optional[str] = None
    created: str = ""

    def tod(self) -> dtime:
        return dtime.fromisoformat(self.at)

    @property
    def next_fire_dt(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.next_fire) if self.next_fire else None

    @property
    def snooze_dt(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.snooze_until) if self.snooze_until else None

    def due_at(self) -> Optional[datetime]:
        """Earliest moment this alarm will ring (scheduled ring or pending snooze), if any."""
        moments = []
        if self.enabled and self.next_fire_dt is not None:
            moments.append(self.next_fire_dt)
        if self.snooze_dt is not None:
            moments.append(self.snooze_dt)
        return min(moments) if moments else None

    @property
    def status(self) -> str:
        if self.snooze_until:
            return "snoozed"
        return "on" if self.enabled else "off"


class Store:
    """Alarms + settings, loaded from and saved to one JSON file."""

    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else default_path()
        self.settings = dict(DEFAULT_SETTINGS)
        self.alarms: List[Alarm] = []
        self.next_id = 1
        self._mtime: Optional[int] = None
        self.load()

    # ---- persistence
    def _stat_mtime(self) -> Optional[int]:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def load(self) -> None:
        self.alarms, self.settings, self.next_id = [], dict(DEFAULT_SETTINGS), 1
        self._mtime = self._stat_mtime()
        if self._mtime is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))  # tolerate a Notepad BOM
            known = {f.name for f in fields(Alarm)}
            alarms = [
                Alarm(**{k: v for k, v in item.items() if k in known})
                for item in raw.get("alarms", [])
            ]
            settings = raw.get("settings", {})
            next_id = int(raw.get("next_id", 1))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise AlarmError(
                f"Cannot read {self.path} ({exc}). Fix the file or delete it to start fresh."
            ) from exc
        self.alarms = alarms
        self.settings.update(settings)
        self.next_id = max(next_id, max((a.id for a in alarms), default=0) + 1)

    def reload_if_changed(self) -> bool:
        """Re-read the file if another process changed it. Returns True when reloaded."""
        if self._stat_mtime() != self._mtime:
            self.load()
            return True
        return False

    def save(self) -> None:
        payload = {
            "version": 1,
            "next_id": self.next_id,
            "settings": self.settings,
            "alarms": [asdict(a) for a in self.alarms],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(tmp_name, self.path)  # atomic: readers never see a half-written file
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        self._mtime = self._stat_mtime()

    # ---- alarm access
    def add(self, **fields_) -> Alarm:
        alarm = Alarm(
            id=self.next_id, created=datetime.now(timezone.utc).isoformat(), **fields_
        )
        self.next_id += 1
        self.alarms.append(alarm)
        return alarm

    def get(self, alarm_id: int) -> Alarm:
        for alarm in self.alarms:
            if alarm.id == alarm_id:
                return alarm
        raise AlarmError(f"No alarm with id {alarm_id}. Use 'list' to see the ids.")

    def remove(self, alarm_id: int) -> None:
        self.alarms.remove(self.get(alarm_id))
