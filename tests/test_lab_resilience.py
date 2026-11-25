"""Store resilience found by the durability lab (B2/B5/B6/B7): locked, read-only, replaced and deleted
database files, and a garbage file that must fail loudly."""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis.hermes import TeresisMemoryProvider

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.dir = Path(self.d.name)
        self.db = self.dir / "r.db"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in (self.dir, self.db):
            try:
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
            except OSError:
                pass
        self.d.cleanup()

    def seed(self, n=3):
        s = MemoryStore(self.db, embedder=None, reranker=None)
        for i in range(n):
            s.remember(f"seed fact {i} about zebra{i} habitat", scope="hermes/lab")
        s.close()

    def test_opening_does_not_wait_for_another_writer(self):
        self.seed()
        holder = sqlite3.connect(self.db, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        self.addCleanup(holder.close)
        t0 = time.time()
        s = MemoryStore(self.db, embedder=None, reranker=None, busy_timeout=0.3)
        self.addCleanup(s.close)
        self.assertLess(time.time() - t0, 2.0, "opening a current-schema database took a write lock")
        self.assertTrue(s.recall("zebra1", scope="hermes/lab"))  # WAL readers are not blocked
        t1 = time.time()
        with self.assertRaises(sqlite3.OperationalError) as cm:
            s.remember("blocked write", scope="hermes/lab")
        self.assertIn("locked", str(cm.exception))
        self.assertLess(time.time() - t1, 3.0)

    @unittest.skipIf(IS_ROOT, "permissions are not enforced for root")
    def test_read_only_file_opens_recalls_and_refuses_writes_clearly(self):
        self.seed()
        for ext in ("-wal", "-shm"):
            Path(str(self.db) + ext).unlink(missing_ok=True)
        os.chmod(self.db, 0o444)
        s = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(s.close)
        self.assertTrue(s.recall("zebra2", scope="hermes/lab"))
        with self.assertRaises(sqlite3.OperationalError) as cm:
            s.remember("nope", scope="hermes/lab")
        self.assertIn("read", str(cm.exception).lower())

    @unittest.skipIf(IS_ROOT, "permissions are not enforced for root")
    def test_read_only_directory_still_recalls(self):
        self.seed()
        for ext in ("-wal", "-shm"):
            Path(str(self.db) + ext).unlink(missing_ok=True)
        os.chmod(self.db, 0o444)
        os.chmod(self.dir, 0o555)
        s = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(s.close)
        self.assertTrue(s.read_only)
        self.assertTrue(s.recall("zebra0", scope="hermes/lab"))
        p = TeresisMemoryProvider(config={"db_path": str(self.db)})
        p.initialize("s", hermes_home=str(self.dir), platform="cli", agent_identity="lab")
        self.addCleanup(p.shutdown)
        self.assertIn("zebra", p.prefetch("zebra habitat"))
        out = json.loads(p.handle_tool_call("memory_remember", {"content": "x y z write", "scope": "hermes/lab"}))
        self.assertIn("read-only", out["error"])

    def test_database_deleted_while_open_is_recreated_and_the_next_write_is_durable(self):
        s = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(s.close)
        s.remember("before the delete kiwi", scope="hermes/lab")
        for f in self.dir.glob("r.db*"):
            f.unlink()
        s.remember("after the delete papaya", scope="hermes/lab")
        self.assertTrue(self.db.exists())
        s.close()
        c = sqlite3.connect(self.db)
        self.addCleanup(c.close)
        self.assertEqual(c.execute("select count(*) from memories where content like '%papaya%'").fetchone()[0], 1)

    def test_database_replaced_while_open_is_followed(self):
        other = self.dir / "other.db"
        o = MemoryStore(other, embedder=None, reranker=None)
        o.remember("restored backup row narwhal", scope="hermes/lab")
        o.close()
        s = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(s.close)
        s.remember("original row okapi", scope="hermes/lab")
        s.close()
        s = MemoryStore(self.db, embedder=None, reranker=None)
        self.addCleanup(s.close)
        for ext in ("-wal", "-shm"):
            Path(str(self.db) + ext).unlink(missing_ok=True)
        os.replace(other, self.db)  # a restore over the live path
        self.assertTrue(s.recall("narwhal", scope="hermes/lab"))
        self.assertFalse(s.recall("okapi", scope="hermes/lab"))

    def test_garbage_file_fails_loudly_and_tools_say_why(self):
        self.db.write_bytes(os.urandom(8192))
        p = TeresisMemoryProvider(config={"db_path": str(self.db)})
        with self.assertRaises(sqlite3.DatabaseError):
            p.initialize("s", hermes_home=str(self.dir), platform="cli", agent_identity="lab")
        out = json.loads(p.handle_tool_call("memory_recall", {"query": "anything"}))
        self.assertIn("not a database", out["error"])
        self.assertEqual(self.db.stat().st_size, 8192)  # never overwrites a file it cannot read


if __name__ == "__main__":
    unittest.main()
