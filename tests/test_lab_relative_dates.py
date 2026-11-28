"""A memory that says "tomorrow" must carry the day it was written (durability lab D4)."""
import calendar
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from teresis import temporal
from teresis.hermes import TeresisMemoryProvider
from teresis.mcp import Server


def utc(y, mo, d, h=0, mi=0):
    return float(calendar.timegm((y, mo, d, h, mi, 0)))


class RelativeDateNoteTests(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        self.addCleanup(self._restore_tz)
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)

    def _restore_tz(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_detects_relative_expressions_only(self):
        for text in ("Dentist is tomorrow at 3pm", "Submit the report next week", "met her yesterday", "back in 3 days",
                     "the demo is this Friday", "ship it tonight", "she moved 2 weeks ago", "due next Monday"):
            self.assertTrue(temporal.has_relative_date(text), text)
        for text in ("User prefers dark mode", "The deploy runs on Fridays", "Dentist is on 2026-11-26 at 3pm",
                     "Tomorrowland festival is in Belgium", "note: yesterdays was a band"):
            self.assertFalse(temporal.has_relative_date(text), text)

    def test_saved_note_uses_the_local_calendar_day(self):
        # 16:30 UTC on the 25th is already the 26th in Tokyo
        note = temporal.saved_note(utc(2026, 11, 25, 16, 30))
        self.assertEqual(note, "[saved Thu 2026-11-26]")

    def test_prefetch_and_tool_recall_anchor_the_relative_phrase(self):
        p = TeresisMemoryProvider(config={"db_path": str(Path(self.d.name) / "r.db")})
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="lab")
        self.addCleanup(p.shutdown)
        p._store.clock = lambda: utc(2026, 11, 24, 3, 0)  # Tue 12:00 JST
        p._store.remember("Dentist appointment is tomorrow at 3pm", scope="hermes/lab", kind="event", importance=0.9)
        p._store.remember("User prefers dark mode editors", scope="hermes/lab", kind="preference")
        p._store.clock = lambda: utc(2026, 12, 3, 3, 0)  # nine days later
        pf = p.prefetch("when is the dentist appointment")
        self.assertIn("tomorrow at 3pm", pf)
        self.assertIn("[saved Tue 2026-11-24]", pf)
        tool = json.loads(p.handle_tool_call("memory_recall", {"query": "dentist appointment"}))
        self.assertIn("[saved Tue 2026-11-24]", tool["result"])
        plain = json.loads(p.handle_tool_call("memory_recall", {"query": "dark mode editors"}))
        self.assertNotIn("[saved", plain["result"])

    def test_clipped_legacy_memory_retains_its_saved_date(self):
        p = TeresisMemoryProvider(config={
            "db_path": str(Path(self.d.name) / "legacy.db"),
            "prefetch_budget_tokens": 2000,
        })
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="lab")
        self.addCleanup(p.shutdown)
        p._store.clock = lambda: utc(2026, 11, 24, 3, 0)
        content = "Dentist appointment details " + "filler " * 800 + "appointment is tomorrow at 3pm"
        p._store.remember(content, scope="hermes/lab", kind="event", importance=0.9)

        tool = json.loads(p.handle_tool_call("memory_recall", {"query": "dentist appointment"}))
        for shown in (p.prefetch("dentist appointment"), tool["result"]):
            self.assertIn("[saved Tue 2026-11-24]", shown)
            self.assertNotIn("tomorrow at 3pm", shown)
            self.assertLess(len(shown), 1500)

    def test_stored_content_and_dedupe_are_unchanged(self):
        p = TeresisMemoryProvider(config={"db_path": str(Path(self.d.name) / "r2.db")})
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="lab")
        self.addCleanup(p.shutdown)
        r = p._store.remember("Dentist appointment is tomorrow at 3pm", scope="hermes/lab")
        self.assertEqual(p._store.get(r.id).content, "Dentist appointment is tomorrow at 3pm")


if __name__ == "__main__":
    unittest.main()
