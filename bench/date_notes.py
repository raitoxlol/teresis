"""Calendar metadata for transcript replay; never edits the source utterance."""

import calendar
import re
from datetime import timedelta


_PHRASE = re.compile(r"\b((?:the\s+)?last\s+(?:week|month|year)|yesterday|tomorrow)\b", re.I)


def _day(d):
    return f"{d.day} {calendar.month_name[d.month]} {d.year}"


def calendar_note(body, spoken_on):
    if spoken_on is None:
        return ""
    notes = {}
    for m in _PHRASE.finditer(body):
        phrase = " ".join(m[1].lower().split())
        if phrase.startswith("the ") or phrase in notes:
            continue
        if phrase == "last month":
            prev = spoken_on.replace(day=1) - timedelta(days=1)
            value = f"{calendar.month_name[prev.month]} {prev.year}"
        elif phrase == "last year":
            value = str(spoken_on.year - 1)
        elif phrase == "last week":
            value = f"week before {_day(spoken_on)}"
        else:
            value = _day(spoken_on + timedelta(days=-1 if phrase == "yesterday" else 1))
        notes[phrase] = value
    return "; ".join(f"{k} = {v}" for k, v in notes.items())
