"""Calendar metadata for transcript replay; never edits the source utterance."""

import calendar
import re
from datetime import timedelta


_PHRASE = re.compile(r"\b(yesterday|tomorrow)\b", re.I)


def _day(d):
    return f"{d.day} {calendar.month_name[d.month]} {d.year}"


def calendar_note(body, spoken_on):
    if spoken_on is None:
        return ""
    notes = {}
    for m in _PHRASE.finditer(body):
        phrase = m[1].lower()
        offset = -1 if phrase == "yesterday" else 1
        notes[phrase] = _day(spoken_on + timedelta(days=offset))
    return "; ".join(f"{k} = {v}" for k, v in notes.items())
