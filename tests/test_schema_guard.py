import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis.store import SCHEMA_VERSION


class SchemaGuardTests(unittest.TestCase):
    def _make_future_db(self, path: Path, user_version: int = 999) -> bytes:
        """A small, clean DB from a hypothetical newer teresis: one sentinel
        table + row, journal_mode DELETE, and a user_version we must refuse."""
        with contextlib.closing(sqlite3.connect(path)) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("CREATE TABLE sentinel (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
            conn.execute("INSERT INTO sentinel (id, note) VALUES (1, 'do not touch')")
            conn.execute(f"PRAGMA user_version={user_version}")
            conn.commit()
        return path.read_bytes()

    def test_rejects_newer_schema_and_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "future.db"
            before = self._make_future_db(db, user_version=999)

            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                MemoryStore(db, embedder=None, reranker=None)

            msg = str(ctx.exception)
            self.assertIn("999", msg)
            self.assertIn(str(SCHEMA_VERSION), msg)

            # Reopen read-only: nothing may have changed.
            with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 999)
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                row = conn.execute("SELECT id, note FROM sentinel WHERE id=1").fetchone()
                self.assertEqual(tuple(row), (1, "do not touch"))
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("sentinel", tables)
                self.assertNotIn("memories", tables)  # no schema DDL may have run

            self.assertEqual(db.read_bytes(), before)

    def test_current_db_reopens_and_recalls_keyed_row(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "current.db"
            with contextlib.closing(MemoryStore(db, embedder=None, reranker=None)) as store:
                r = store.remember("Editor is VS Code", scope="user", key="user.editor")

            with contextlib.closing(MemoryStore(db, embedder=None, reranker=None)) as reopened:
                hits = reopened.recall("editor", scope="user")
                self.assertEqual(hits[0].id, r.id)

    def test_lower_schema_version_is_accepted_and_upgraded(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "legacy.db"
            with contextlib.closing(MemoryStore(db, embedder=None, reranker=None)) as store:
                r = store.remember("Legacy fact", scope="p", key="legacy.key")

            # Stamp it as an older teresis and reopen: accepted, upgraded in place,
            # and the existing data is still reachable.
            with contextlib.closing(sqlite3.connect(db)) as conn:
                conn.execute("PRAGMA user_version=2")
                conn.commit()

            with contextlib.closing(MemoryStore(db, embedder=None, reranker=None)) as reopened:
                hits = reopened.recall("legacy", scope="p")
                self.assertEqual(hits[0].id, r.id)

            with contextlib.closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()