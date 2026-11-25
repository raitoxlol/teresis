"""One shared database must not let one Hermes profile read, forge or delete another's memories
through tool arguments (durability lab E7)."""
import json
import tempfile
import unittest
from pathlib import Path

from teresis.hermes import TeresisMemoryProvider


class ScopeGuardTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.db = str(Path(self.d.name) / "shared.db")
        self.alice = self.provider("alice")
        self.bob = self.provider("bob")
        r = self.call(self.alice, "memory_remember", content="alice private note: rooftop garden code cobalt-fern", scope="hermes/alice")
        self.alice_id = r["id"]

    def provider(self, identity, **cfg):
        p = TeresisMemoryProvider(config={"db_path": self.db, **cfg})
        p.initialize(f"s-{identity}", hermes_home=self.d.name, platform="cli", agent_identity=identity)
        self.addCleanup(p.shutdown)
        return p

    @staticmethod
    def call(p, name, **args):
        return json.loads(p.handle_tool_call(name, args))

    def test_cannot_read_another_profiles_scope(self):
        for tool, args in (("memory_recall", {"query": "rooftop garden code", "scope": "hermes/alice"}),
                           ("memory_context", {"scope": "hermes/alice", "query": "rooftop"}),
                           ("memory_conflicts", {"scope": "hermes/alice"}),
                           ("memory_history", {"scope": "hermes/alice", "key": "x"}),
                           ("memory_history", {"id": self.alice_id})):
            out = self.call(self.bob, tool, **args)
            self.assertIn("another Hermes profile", out.get("error", ""), (tool, out))
            self.assertNotIn("cobalt-fern", json.dumps(out))

    def test_cannot_delete_update_or_rate_another_profiles_memory(self):
        for tool, args in (("memory_forget", {"id": self.alice_id}),
                           ("memory_forget", {"scope": "hermes/alice", "key": "k"}),
                           ("memory_update", {"id": self.alice_id, "content": "tampered by bob"}),
                           ("memory_feedback", {"id": self.alice_id, "helpful": False})):
            self.assertIn("another Hermes profile", self.call(self.bob, tool, **args).get("error", ""), tool)
        row = self.alice._store.get(self.alice_id)
        self.assertIsNone(row.deleted_at)
        self.assertIn("cobalt-fern", row.content)

    def test_cannot_forge_a_memory_into_another_profiles_scope(self):
        out = self.call(self.bob, "memory_remember", content="bob forged entry", scope="hermes/alice")
        self.assertIn("another Hermes profile", out.get("error", ""))
        self.assertEqual(self.alice._store._conn.execute("select count(*) from memories where content like '%forged%'").fetchone()[0], 0)

    def test_stats_do_not_list_other_profiles_scopes(self):
        out = self.call(self.bob, "memory_stats")
        self.assertNotIn("hermes/alice", json.dumps(out))

    def test_shared_and_own_scopes_still_work(self):
        for scope in ("hermes/bob", "hermes/bob/project", "user", "global", "project/acme", None):
            args = {"content": f"bob note for {scope} zebra", **({"scope": scope} if scope else {})}
            out = self.call(self.bob, "memory_remember", **args)
            self.assertIn("id", out, (scope, out))
            found = self.call(self.bob, "memory_recall", query="zebra", **({"scope": scope} if scope else {}))
            self.assertIn("memories", found, (scope, found))
        own = self.call(self.bob, "memory_forget", id=self.call(self.bob, "memory_remember", content="bob own temp note", scope="hermes/bob")["id"])
        self.assertEqual(own["forgotten"], 1)

    def test_extra_scopes_from_config_are_readable(self):
        carol = self.provider("carol", extra_scopes="user,hermes/alice")
        self.assertIn("memories", self.call(carol, "memory_recall", query="rooftop garden", scope="hermes/alice"))

    def test_scope_list_or_odd_types_are_rejected_not_crashed(self):
        out = self.call(self.bob, "memory_recall", query="rooftop", scope=["hermes/alice"])
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
