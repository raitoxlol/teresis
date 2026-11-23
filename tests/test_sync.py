import json
import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore
from teresis import sync as S


class CryptoTests(unittest.TestCase):
    def test_round_trip(self):
        payload = b'{"hello": "world"}\n' * 40
        bundle = S.encrypt(payload, "correct horse battery staple")
        self.assertEqual(bundle["format"], S.FORMAT)
        self.assertNotIn(b"hello", json.dumps(bundle).encode())
        self.assertEqual(S.decrypt(bundle, "correct horse battery staple"), payload)

    def test_wrong_passphrase_rejected(self):
        bundle = S.encrypt(b"secret", "right")
        with self.assertRaises(ValueError):
            S.decrypt(bundle, "wrong")

    def test_tampered_ciphertext_rejected(self):
        bundle = S.encrypt(b"secret", "pw")
        raw = bytearray(__import__("base64").b64decode(bundle["ciphertext"]))
        raw[0] ^= 1
        bundle["ciphertext"] = __import__("base64").b64encode(bytes(raw)).decode()
        with self.assertRaises(ValueError):
            S.decrypt(bundle, "pw")

    def test_ciphertext_is_not_plaintext(self):
        bundle = S.encrypt(b"A" * 128, "pw")
        self.assertEqual(len(__import__("base64").b64decode(bundle["ciphertext"])), 128)

    def test_passphrase_from_env(self):
        import os

        os.environ["TERESIS_TEST_KEY"] = "from-env"
        try:
            self.assertEqual(S.passphrase("TERESIS_TEST_KEY"), "from-env")
        finally:
            os.environ.pop("TERESIS_TEST_KEY", None)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.a = MemoryStore(Path(self.d.name) / "a.db", embedder=None)
        self.b = MemoryStore(Path(self.d.name) / "b.db", embedder=None)

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.d.cleanup()

    def test_insert_and_idempotent(self):
        self.b.remember("Atlas uses Postgres", scope="p")
        recs = list(self.b.export())
        self.assertEqual(S.merge(self.a, recs)["inserted"], 1)
        self.assertEqual(S.merge(self.a, recs)["inserted"], 0)
        self.assertEqual(S.merge(self.a, recs)["skipped"], 1)

    def test_newer_wins(self):
        m = self.a.remember("Atlas uses Postgres", scope="p", key="atlas.db")
        rec = next(r for r in self.a.export() if r["id"] == m.id)
        rec["content"] = "Atlas uses Postgres 17"
        rec["updated_at"] = rec["updated_at"] + 60
        res = S.merge(self.a, [rec])
        self.assertEqual(res["updated"], 1)
        self.assertEqual(self.a.history(scope="p", key="atlas.db")[-1].content, "Atlas uses Postgres 17")

    def test_older_is_skipped(self):
        self.a.remember("Atlas uses Postgres 17", scope="p")
        rec = next(r for r in self.a.export())
        old = {**rec, "content": "Atlas uses MySQL", "updated_at": rec["updated_at"] - 60}
        self.assertEqual(S.merge(self.a, [old])["skipped"], 1)
        self.assertEqual(self.a.get(rec["id"]).content, "Atlas uses Postgres 17")

    def test_keyed_slot_supersedes_across_machines(self):
        self.a.remember("Editor is VS Code", scope="user", key="user.editor")
        self.b.remember("Editor is Neovim", scope="user", key="user.editor")
        rec = next(r for r in self.b.export() if r["key"] == "user.editor")
        rec["updated_at"] = rec["updated_at"] + 120
        res = S.merge(self.a, [rec])
        self.assertEqual(res["superseded"], 1)
        history = self.a.history(scope="user", key="user.editor")
        self.assertEqual(len(history), 2)
        active = [m for m in history if m.superseded_by is None]
        self.assertEqual(active[0].content, "Editor is Neovim")

    def test_dry_run_writes_nothing(self):
        self.b.remember("Atlas uses Postgres", scope="p")
        res = S.merge(self.a, list(self.b.export()), dry_run=True)
        self.assertEqual(res["inserted"], 1)
        self.assertEqual(self.a.stats()["active"], 0)

    def test_bad_records_skipped(self):
        self.assertEqual(S.merge(self.a, [{"id": "x"}, {"content": "y"}])["skipped"], 2)

    def test_merge_rebuilds_entities(self):
        self.b.remember("Atlas ships on Fly.io", scope="p")
        S.merge(self.a, list(self.b.export()))
        mem = self.a.recall("atlas", scope="p", k=1, touch=False)[0]
        self.assertTrue(self.a.entities_for(mem.id))


class BundleTests(unittest.TestCase):
    def test_export_import_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src = MemoryStore(Path(d) / "src.db", embedder=None)
            dst = MemoryStore(Path(d) / "dst.db", embedder=None)
            try:
                src.remember("Atlas uses Postgres", scope="p", key="atlas.db")
                src.remember("Priya owns billing", scope="p")
                out = Path(d) / "bundle.json"
                info = S.export_bundle(src, out, "pw", None)
                self.assertEqual(info["memories"], 2)
                self.assertNotIn("Postgres", out.read_text())
                recs = S.read_bundle(out, "pw")
                self.assertEqual(len(recs), 2)
                self.assertEqual(S.merge(dst, recs)["inserted"], 2)
                self.assertEqual(dst.recall("atlas postgres", scope="p", k=2, touch=False)[0].content,
                                 "Atlas uses Postgres")
            finally:
                src.close()
                dst.close()

    def test_scope_filter(self):
        with tempfile.TemporaryDirectory() as d:
            src = MemoryStore(Path(d) / "src.db", embedder=None)
            try:
                src.remember("one", scope="a")
                src.remember("two", scope="b")
                out = Path(d) / "b.json"
                self.assertEqual(S.export_bundle(src, out, "pw", ["a"])["memories"], 1)
            finally:
                src.close()


if __name__ == "__main__":
    unittest.main()
