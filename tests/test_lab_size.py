"""Memory size and tool-output bounds (durability lab D8: a 360 KB memory was accepted and tool recall
returned 836 KB into the model context)."""
import json
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis.hermes import TeresisMemoryProvider
from teresis.mcp import MAX_MEMORY_CHARS, MAX_TOOL_OUTPUT_CHARS, Server


class SizeBoundTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.store = MemoryStore(Path(self.d.name) / "s.db", embedder=None, reranker=None)
        self.addCleanup(self.store.close)
        self.server = Server(self.store, default_scope="hermes/lab")

    def test_overlong_tool_write_is_refused_with_advice(self):
        with self.assertRaises(ValueError) as cm:
            self.server.call_tool("memory_remember", {"content": "orchard " + "giant " * 60000})
        self.assertIn(str(MAX_MEMORY_CHARS), str(cm.exception))
        self.assertIn("summar", str(cm.exception))
        self.assertEqual(self.store._conn.execute("select count(*) from memories").fetchone()[0], 0)

    def test_update_cannot_grow_a_memory_past_the_limit(self):
        r = self.store.remember("small fact", scope="hermes/lab")
        with self.assertRaises(ValueError):
            self.server.call_tool("memory_update", {"id": r.id, "content": "x " * MAX_MEMORY_CHARS})

    def test_limit_is_inclusive(self):
        text = ("a" * (MAX_MEMORY_CHARS - 1))
        self.server.call_tool("memory_remember", {"content": text})
        self.assertEqual(self.store._conn.execute("select count(*) from memories").fetchone()[0], 1)

    def test_recall_output_is_bounded_even_with_huge_legacy_rows(self):
        for i in range(25):
            self.store.remember(f"orchard giant {i} " + "word " * 9000, scope="hermes/lab")
        text, data = self.server.call_tool("memory_recall", {"query": "orchard giant", "k": 25})
        self.assertLessEqual(len(text), MAX_TOOL_OUTPUT_CHARS + 200)
        self.assertLessEqual(len(json.dumps(data, default=str)), MAX_TOOL_OUTPUT_CHARS * 2)
        self.assertIn("truncated", text)

    def test_provider_tool_reply_and_prefetch_are_bounded(self):
        p = TeresisMemoryProvider(config={"db_path": str(Path(self.d.name) / "p.db")})
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="lab")
        self.addCleanup(p.shutdown)
        for i in range(15):
            p._store.remember(f"orchard note {i} irrigation valve " + "filler " * 9000, scope="hermes/lab")
        reply = p.handle_tool_call("memory_recall", {"query": "orchard irrigation valve", "k": 15})
        self.assertLess(len(reply), MAX_TOOL_OUTPUT_CHARS * 3)
        self.assertLess(len(p.prefetch("orchard irrigation valve note")), 6000)

    def test_normal_memories_are_not_clipped(self):
        r = self.store.remember("User prefers dark mode and tabs, and deploys on Fridays", scope="hermes/lab")
        text, data = self.server.call_tool("memory_recall", {"query": "dark mode tabs"})
        self.assertIn("User prefers dark mode and tabs, and deploys on Fridays", text)
        self.assertNotIn("truncated", text)


if __name__ == "__main__":
    unittest.main()
