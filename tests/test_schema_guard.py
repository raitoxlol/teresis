import contextlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teresis import MemoryStore
from teresis import store as store_mod
from teresis.store import SCHEMA_VERSION

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


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

    def _assert_untouched_future(self, db: Path, before: bytes) -> None:
        self.assertEqual(db.read_bytes(), before)
        with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 999)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("memories", tables)

    @contextlib.contextmanager
    def _spy_connect(self):
        """Record every connection MemoryStore opens (and whether it was the read-only one)."""
        real = MemoryStore._connect
        opened: list[tuple[bool, sqlite3.Connection]] = []

        def spy(store, *, immutable=False):
            conn = real(store, immutable=immutable)
            opened.append((immutable, conn))
            return conn

        with mock.patch.object(MemoryStore, "_connect", spy):
            yield opened

    def _assert_all_closed(self, conns) -> None:
        for conn in conns:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

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

    @unittest.skipIf(IS_ROOT, "permissions are not enforced for root")
    def test_rejects_newer_schema_on_the_read_only_fallback(self):
        # A WAL file in a read-only directory without its -shm cannot be opened normally, so the
        # store falls back to an immutable read-only connection. That path must refuse it too.
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "ro"
            folder.mkdir()
            db = folder / "future.db"
            self._make_future_db(db, user_version=999)
            with contextlib.closing(sqlite3.connect(db)) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
            for ext in ("-wal", "-shm"):
                Path(str(db) + ext).unlink(missing_ok=True)
            before = db.read_bytes()
            os.chmod(db, 0o444)
            os.chmod(folder, 0o555)
            try:
                with self._spy_connect() as opened, self.assertRaises(sqlite3.DatabaseError) as ctx:
                    MemoryStore(db, embedder=None, reranker=None)
                self.assertIn("999", str(ctx.exception))
                self.assertEqual([immutable for immutable, _ in opened], [False, True])  # the fallback ran
                self._assert_all_closed(conn for _, conn in opened)
                self.assertEqual(sorted(p.name for p in folder.iterdir()), ["future.db"])
            finally:
                os.chmod(folder, 0o755)
                os.chmod(db, 0o644)
            self._assert_untouched_future(db, before)

    def test_rejects_newer_schema_swapped_in_while_open(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "live.db"
            future = Path(d) / "future.db"
            before = self._make_future_db(future, user_version=999)
            with contextlib.closing(MemoryStore(db, embedder=None, reranker=None)) as store:
                store.remember("current row okapi", scope="p")
                old = store._conn
                for ext in ("-wal", "-shm"):
                    Path(str(db) + ext).unlink(missing_ok=True)
                os.replace(future, db)  # e.g. a backup from a newer teresis restored over the live path
                with self._spy_connect() as opened:
                    for call in (lambda: store.recall("okapi", scope="p"),
                                 lambda: store.remember("must not land", scope="p"),
                                 lambda: store.stats()):
                        with self.assertRaises(sqlite3.DatabaseError) as ctx:
                            call()
                        self.assertIn("999", str(ctx.exception))
                self.assertEqual(len(opened), 3)  # every call re-checks; none keeps a connection
                self._assert_all_closed([old, *(conn for _, conn in opened)])
            self._assert_untouched_future(db, before)

    def test_newer_schema_seen_under_the_write_lock_aborts_the_ddl(self):
        # Another process upgrades the file between the first version read and BEGIN IMMEDIATE:
        # the re-check inside the transaction refuses it, and no DDL or stamp is committed.
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "raced.db"
            self._make_future_db(db, user_version=999)
            real = store_mod._read_user_version
            reads = []

            def stale_first(conn):
                reads.append(1)
                return 2 if len(reads) == 1 else real(conn)

            with mock.patch.object(store_mod, "_read_user_version", side_effect=stale_first), \
                    self._spy_connect() as opened, self.assertRaises(sqlite3.DatabaseError) as ctx:
                MemoryStore(db, embedder=None, reranker=None)
            self.assertIn("999", str(ctx.exception))
            self.assertEqual(len(reads), 2)
            self._assert_all_closed(conn for _, conn in opened)
            with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 999)
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(tables, {"sentinel"})


if __name__ == "__main__":
    unittest.main()
