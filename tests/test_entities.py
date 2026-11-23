import tempfile
import unittest
from pathlib import Path

from teresis import MemoryStore, Weights
from teresis import entities as E


class ExtractTests(unittest.TestCase):
    def keys(self, text):
        return {e.key for e in E.extract(text)}

    def test_explicit_signals(self):
        got = self.keys("Deploy on [[project:atlas]] with @priya against git.cafe/w/teresis at ~/Projects/atlas")
        self.assertIn("atlas", got)
        self.assertIn("priya", got)
        self.assertIn("git.cafe", got)
        self.assertIn("w/teresis", got)
        self.assertIn("~/projects/atlas", got)

    def test_wiki_kind(self):
        (e,) = [e for e in E.extract("owner is [[person:Ada Lovelace]]")]
        self.assertEqual((e.key, e.kind, e.explicit), ("ada lovelace", "person", True))

    def test_noise_rejected(self):
        got = self.keys("Fixed the migration. Deploy pipeline uses GitHub Actions. Updated the docs.")
        self.assertNotIn("fixed", got)
        self.assertNotIn("deploy", got)
        self.assertNotIn("updated", got)
        self.assertIn("github actions", got)

    def test_proper_noun_is_inferred(self):
        (e,) = [e for e in E.extract("Priya owns billing")]
        self.assertEqual(e.key, "priya")
        self.assertFalse(e.explicit)
        self.assertLess(e.weight, 1.0)

    def test_limit_and_empty(self):
        self.assertEqual(E.extract(""), [])
        self.assertLessEqual(len(E.extract("[[a1]] [[a2]] [[a3]] [[a4]] [[a5]] [[a6]] [[a7]] [[a8]] "
                                          "[[a9]] [[a10]] [[a11]] [[a12]] [[a13]] [[a14]] [[a15]] [[a16]]")), 14)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.s = MemoryStore(Path(self.d.name) / "g.db", embedder=None)

    def tearDown(self):
        self.s.close()
        self.d.cleanup()

    def test_entities_linked_on_write(self):
        m = self.s.remember("Atlas uses PostgreSQL 16", scope="p")
        names = {e["name"] for e in self.s.entities_for(m.id)}
        self.assertIn("Atlas", names)

    def test_explicit_link_and_unlink(self):
        m = self.s.remember("Rolled out the refund flow", scope="p")
        key = self.s.link(m.id, "Atlas", kind="project")
        self.assertEqual(key, "atlas")
        self.assertTrue(any(e["key"] == "atlas" and e["explicit"] for e in self.s.entities_for(m.id)))
        self.assertEqual(self.s.unlink(m.id, "Atlas"), 1)
        self.assertFalse(any(e["key"] == "atlas" for e in self.s.entities_for(m.id)))

    def test_multi_hop_recall(self):
        self.s.remember("Priya owns the billing service", scope="p")
        self.s.remember("Priya is on leave through October", scope="p")
        self.s.remember("The data warehouse is Snowflake", scope="p")
        hits = self.s.recall("billing service", scope="p", k=5, touch=False)
        texts = [m.content for m in hits]
        self.assertIn("Priya owns the billing service", texts)
        self.assertIn("Priya is on leave through October", texts)  # reached only through the entity
        self.assertNotIn("The data warehouse is Snowflake", texts)

    def test_hop_can_be_disabled(self):
        self.s.remember("Priya owns the billing service", scope="p")
        self.s.remember("Priya is on leave through October", scope="p")
        self.s.w = Weights(entity_hop=0.0)
        texts = [m.content for m in self.s.recall("billing service", scope="p", k=5, touch=False)]
        self.assertNotIn("Priya is on leave through October", texts)

    def test_hop_respects_scope(self):
        self.s.remember("Priya owns the billing service", scope="project/a")
        self.s.remember("Priya is on leave through October", scope="project/b")
        texts = [m.content for m in self.s.recall("billing service", scope="project/a", k=5, touch=False)]
        self.assertNotIn("Priya is on leave through October", texts)

    def test_one_mention_is_not_traversable(self):
        self.s.remember("Quantum flux capacitor notes", scope="p")
        self.s.remember("Something unrelated entirely", scope="p")
        self.assertEqual(self.s.recall("flux capacitor", scope="p", k=5, touch=False)[0].content,
                         "Quantum flux capacitor notes")

    def test_reindex_and_stats(self):
        self.s.remember("Atlas ships on Fly.io", scope="p")
        before = self.s.stats()
        self.assertGreater(before["entities"], 0)
        self.assertEqual(before["links"], len(self.s.entities_for(self.s.get(
            self.s.recall("atlas", scope="p", k=1, touch=False)[0].id).id)))
        out = self.s.reindex_entities()
        self.assertEqual(out["memories"], 1)
        self.assertEqual(self.s.stats()["entities"], out["entities"])

    def test_top_entities(self):
        self.s.remember("Atlas uses Postgres", scope="p")
        self.s.remember("Atlas deploys on Fly.io", scope="p")
        top = self.s.top_entities(limit=5)
        self.assertEqual(top[0]["key"], "atlas")
        self.assertGreaterEqual(top[0]["memories"], 2)

    def test_import_links_entities(self):
        m = self.s.remember("Nucbox runs Ollama", scope="p")
        recs = [r for r in self.s.export()]
        other = MemoryStore(Path(self.d.name) / "o.db", embedder=None)
        try:
            self.assertEqual(other.import_(recs), 1)
            self.assertTrue(other.entities_for(m.id))
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
