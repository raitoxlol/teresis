"""Forget must actually forget (found by the Teresis durability lab, scenario D2/D3)."""
import json
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis.hermes import TeresisMemoryProvider
from teresis.mcp import Server

TOKEN = "velociraptor-ninetyone"


def disk_has(db: Path, needle: str) -> bool:
    for ext in ("", "-wal", "-shm"):
        f = Path(str(db) + ext)
        if f.exists() and needle.encode() in f.read_bytes():
            return True
    return False


class ForgetIsRealTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = Path(self.d.name) / "f.db"
        self.store = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(self.d.cleanup)
        self.addCleanup(self.store.close)
        self.server = Server(self.store, default_scope="hermes/lab")

    def _nothing_left(self, needle=TOKEN):
        c = self.store._conn
        self.assertEqual(c.execute("select count(*) from memories where content like ?", (f"%{needle}%",)).fetchone()[0], 0)
        self.assertEqual(c.execute("select count(*) from memories_fts where memories_fts match ?", (needle.split("-")[0],)).fetchone()[0], 0)
        self.assertEqual(c.execute("select count(*) from memories_tri where memories_tri match ?", (needle.split("-")[0],)).fetchone()[0], 0)
        self.assertFalse(any(needle in json.dumps(r) for r in self.store.export()))
        self.assertFalse(disk_has(self.db, needle), "forgotten text is still in the database or WAL file")

    def test_tool_forget_removes_row_indexes_export_and_bytes(self):
        r = self.store.remember(f"the vault door code is {TOKEN}", scope="hermes/lab")
        _, data = self.server.call_tool("memory_forget", {"id": r.id})
        self.assertEqual(data["forgotten"], 1)
        self._nothing_left()

    def test_tool_forget_by_key_removes_every_version(self):
        self.store.remember(f"door code is {TOKEN}-old", scope="user", key="user.door")
        self.store.remember("door code is rotated-new-value", scope="user", key="user.door")
        self.server.call_tool("memory_forget", {"scope": "user", "key": "user.door"})
        self.assertEqual(self.store._conn.execute("select count(*) from memories").fetchone()[0], 0)
        self._nothing_left()

    def test_forget_by_id_also_removes_the_older_versions_it_replaced(self):
        old = self.store.remember(f"door code is {TOKEN}-old", scope="user", key="user.door")
        new = self.store.remember("door code is rotated-new-value", scope="user", key="user.door")
        self.server.call_tool("memory_forget", {"id": new.id})
        self.assertIsNone(self.store.get(old.id))
        self._nothing_left()

    def test_hard_false_keeps_a_recoverable_soft_delete(self):
        r = self.store.remember("soft delete me flamingo", scope="hermes/lab")
        self.server.call_tool("memory_forget", {"id": r.id, "hard": False})
        row = self.store.get(r.id)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row.deleted_at)

    def test_hard_delete_drops_orphan_entities(self):
        r = self.store.remember("Zanzibar Quartz Holdings reported the number", scope="hermes/lab")
        self.assertGreater(self.store._conn.execute("select count(*) from entities").fetchone()[0], 0)
        self.store.forget(r.id, hard=True)
        left = self.store._conn.execute("select count(*) from entities e where not exists "
                                        "(select 1 from memory_entities me where me.entity_key=e.key)").fetchone()[0]
        self.assertEqual(left, 0)
        self.assertFalse(disk_has(self.db, "Zanzibar Quartz"))

    def test_other_memories_survive_a_hard_delete(self):
        keep = self.store.remember("keep this narwhal fact", scope="hermes/lab")
        gone = self.store.remember(f"drop this {TOKEN} fact", scope="hermes/lab")
        self.store.forget(gone.id, hard=True)
        self.assertEqual([m.id for m in self.store.recall("narwhal", scope="hermes/lab")], [keep.id])
        self.assertEqual(self.store._conn.execute("pragma integrity_check").fetchone()[0], "ok")


class ProviderForgetTests(unittest.TestCase):
    def test_hermes_tool_forget_is_a_real_delete(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "p.db"
            p = TeresisMemoryProvider(config={"db_path": str(db)})
            p.initialize("s", hermes_home=d, platform="cli", agent_identity="lab")
            out = json.loads(p.handle_tool_call("memory_remember", {"content": f"private {TOKEN} note", "scope": "hermes/lab"}))
            res = json.loads(p.handle_tool_call("memory_forget", {"id": out["id"]}))
            self.assertEqual(res["forgotten"], 1)
            self.assertFalse(disk_has(db, TOKEN))
            p.shutdown()


if __name__ == "__main__":
    unittest.main()
