import json
import os
import sys
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request
from contextvars import ContextVar
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

from teresis import embed
from teresis.hermes import TeresisMemoryProvider
from teresis.store import MemoryStore


class HermesIsolationTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.Homes = {p: Path(d.name) / p for p in ("atlas", "birch", "cedar")}
        self.active = ContextVar("profile", default="atlas")
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: self.Homes[self.active.get()]
        secrets = types.ModuleType("agent.secret_scope")
        self.keys = {"atlas": "fixture-atlas-key", "birch": "fixture-birch-key"}
        self.secret_reads = []

        def get_secret(name):
            self.assertEqual(name, "TERESIS_EMBED_KEY")
            self.secret_reads.append(self.active.get())
            return self.keys.get(self.active.get())

        secrets.get_secret = get_secret
        self._keep(patch.dict(sys.modules, {"hermes_constants": constants, "agent.secret_scope": secrets}))
        self._keep(patch.dict(os.environ, {
            "TERESIS_EMBED": "openai", "TERESIS_EMBED_MODEL": "wrong-global",
            "TERESIS_EMBED_URL": "https://ambient.invalid/v1",
            "TERESIS_EMBED_KEY": "fixture-ambient-key", "TERESIS_EMBED_TIMEOUT": "23",
            "TERESIS_RERANK": "fastembed", "TERESIS_RERANK_MODEL": "wrong-global-ranker",
        }))
        self.egress = self._keep(patch("teresis.embed._post"))
        self.egress.side_effect = lambda _, body, *a, **k: {
            "data": [{"embedding": [1, 0], "index": i} for i in range(len(body["input"]))],
            "embeddings": [[1, 0] for _ in body["input"]],
        }
        self.rerank = self._keep(patch("teresis.embed.FastEmbedReranker"))

    def _keep(self, mgr):
        value = mgr.start()
        self.addCleanup(mgr.stop)
        return value

    def provider(self, name, **settings):
        self.active.set(name)
        home = self.Homes[name]
        p = TeresisMemoryProvider(config={"db_path": str(home / "synthetic.db"), **settings})
        self.addCleanup(p.shutdown)
        p.initialize(f"session-{name}", hermes_home=str(home), agent_identity=name)
        return p

    def remember(self, p, profile):
        self.active.set(profile)
        result = p.handle_tool_call("memory_remember", {"content": "Synthetic cedar orbit az843"})
        return json.loads(result)["id"]

    def test_two_profiles_use_only_their_endpoint_key_and_settings(self):
        base = os.environ.copy()
        atlas = self.provider("atlas", embed="openai", embed_model="atlas-model",
                              embed_url="https://atlas.invalid/v1", embed_timeout=19,
                              rerank="fastembed", rerank_model="atlas-ranker")
        birch = self.provider("birch", embed="openai", embed_model="birch-model",
                              embed_url="https://birch.invalid/v1")
        self.remember(birch, "birch")
        birch_call = self.egress.call_args
        self.remember(atlas, "atlas")
        atlas_call = self.egress.call_args
        self.assertEqual(birch_call.args[0], "https://birch.invalid/v1/embeddings")
        self.assertEqual(birch_call.args[1]["model"], "birch-model")
        self.assertEqual(birch_call.args[2]["Authorization"], "Bearer fixture-birch-key")
        self.assertEqual(atlas_call.args[0], "https://atlas.invalid/v1/embeddings")
        self.assertEqual(atlas_call.args[1]["model"], "atlas-model")
        self.assertEqual(atlas_call.args[2]["Authorization"], "Bearer fixture-atlas-key")
        self.assertEqual(atlas_call.kwargs, {"timeout": 19, "no_redirect": True})
        self.assertEqual(birch_call.kwargs, {"timeout": 120, "no_redirect": True})
        self.rerank.assert_called_once_with("atlas-ranker")
        self.assertEqual(self.secret_reads, ["birch", "atlas"])
        self.assertEqual(os.environ.copy(), base)

    def test_lexical_profile_and_wrong_owner_never_send_data_or_read_secret(self):
        atlas = self.provider("atlas", embed="openai", embed_model="atlas-model",
                              embed_url="https://atlas.invalid/v1")
        cedar = self.provider("cedar")
        mid = self.remember(cedar, "cedar")
        hits = json.loads(cedar.handle_tool_call("memory_recall", {"query": "az843"}))["memories"]
        self.assertEqual([m["id"] for m in hits], [mid])
        with self.assertRaisesRegex(RuntimeError, "owning Hermes profile"):
            atlas._store.embedder.embed(["Synthetic unbound record"])
        self.egress.assert_not_called()
        self.rerank.assert_not_called()
        self.assertEqual(self.secret_reads, [])

    def test_profile_missing_key_does_not_use_process_value_and_anon_never_asks(self):
        cedar = self.provider("cedar", embed="openai", embed_model="m",
                              embed_url="https://anonymous.invalid/v1")
        self.remember(cedar, "cedar")
        self.assertEqual(self.egress.call_args.args[2], {})
        self.assertEqual(self.secret_reads, ["cedar"])
        anon = self.provider("atlas", embed="openai", embed_model="m",
                             embed_url="http://localhost:9999/v1", embed_auth="none")
        self.remember(anon, "atlas")
        self.assertEqual(self.egress.call_args.args[2], {})
        self.assertEqual(self.secret_reads, ["cedar"])

    def test_insecure_remote_bearer_is_not_sent_and_query_redacts_before_egress(self):
        atlas = self.provider("atlas", embed="openai", embed_model="m",
                              embed_url="http://atlas.invalid/v1")
        with self.assertRaisesRegex(ValueError, "require HTTPS"):
            atlas._store.embedder.embed(["Synthetic private data"])
        self.egress.assert_not_called()
        birch = self.provider("birch", embed="ollama", embed_model="local")
        self.remember(birch, "birch")
        credential = "sk-" + ("qa" * 25)
        birch.handle_tool_call("memory_recall", {"query": f"az843 {credential}"})
        body = self.egress.call_args.args[1]
        self.assertIn("[REDACTED:openai_key]", body["input"][0])
        self.assertNotIn(credential, str(body))
        self.assertEqual(self.egress.call_args.args[0], "http://localhost:11434/api/embed")

    def test_pending_capture_is_local_and_retries_only_in_its_owning_profile(self):
        shared = self.Homes["atlas"].parent / "shared.db"
        settings = {"embed": "openai", "embed_model": "synthetic", "db_path": str(shared)}
        atlas = self.provider("atlas", embed_url="https://atlas.invalid/v1", **settings)
        started, release, captured = Event(), Event(), Event()
        original_post = self.egress.side_effect

        def stalled_post(*args, **kwargs):
            started.set()
            release.wait(5)
            return original_post(*args, **kwargs)

        self.egress.side_effect = stalled_post

        def capture():
            atlas.sync_turn("For future reference, I prefer using the cobalt terminal.", "Got it.")
            atlas.sync_turn("We always label backups with juniper.", "Got it.")
            captured.set()

        thread = Thread(target=capture, daemon=True)
        indexer = getattr(atlas, "_capture_indexer", None)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertTrue(captured.wait(2), "capture waited for embedding")
            atlas.shutdown()
            with MemoryStore(shared, embedder=None, reranker=None) as store:
                self.assertTrue(store.recall("cobalt", kinds=["episode"]))
                self.assertTrue(store.recall("cobalt", kinds=["preference"]))
                self.assertTrue(store.recall("juniper", kinds=["episode"]))
        finally:
            release.set()
            thread.join()
            if indexer:
                indexer.thread.join(5)

        self.egress.side_effect = original_post
        self.egress.reset_mock()
        birch = self.provider("birch", embed_url="https://birch.invalid/v1", **settings)
        birch.sync_turn("The lilac archive is on the shelf.", "Got it.")
        restarted = self.provider("atlas", embed_url="https://atlas.invalid/v1", **settings)
        # Wait for both independent workers to complete their committed jobs.
        deadline = time.monotonic() + 5
        while any(p._store.pending_embeddings(p._capture_indexer.owner) for p in (restarted, birch)):
            self.assertLess(time.monotonic(), deadline, "pending jobs did not index after restart")
            time.sleep(0.01)
        calls = {host: [] for host in ("birch", "atlas")}
        for call in self.egress.call_args_list:
            url, body, headers = call.args
            profile = urllib.parse.urlsplit(url).hostname.split(".")[0]
            self.assertEqual(headers["Authorization"], f"Bearer fixture-{profile}-key")
            calls[profile].extend(body["input"])
        self.assertTrue(any("juniper" in text for text in calls["atlas"]))
        self.assertTrue(any("lilac" in text for text in calls["birch"]))
        self.assertFalse(any("juniper" in text or "cobalt" in text for text in calls["birch"]))

    def test_rejected_capture_does_not_block_later_vectors(self):
        settings = {"embed": "openai", "embed_model": "synthetic",
                    "embed_url": "https://atlas.invalid/v1", "auto_extract": False}
        provider = self.provider("atlas", **settings)
        indexer = provider._capture_indexer
        indexer.stop()
        indexer.thread.join(5)
        provider.sync_turn("The synthetic rejected row uses a cobalt marker.", "Understood.")
        provider.sync_turn("The healthy juniper archive is on the shelf.", "Understood.")
        provider.shutdown()
        accepted = self.egress.side_effect

        failed = Event()
        with patch("teresis.hermes.log.warning", side_effect=lambda *_: failed.set()):
            self.egress.side_effect = urllib.error.HTTPError("https://atlas.invalid/v1", 503, "unavailable", None, None)
            unavailable = self.provider("atlas", **settings)
            self.assertTrue(failed.wait(3))
            unavailable_indexer = unavailable._capture_indexer
            unavailable.shutdown()
            unavailable_indexer.thread.join(5)
        self.egress.assert_called_once()
        self.assertEqual(len(self.egress.call_args.args[1]["input"]), 2)
        self.egress.reset_mock()

        def post(url, body, headers, **kwargs):
            if any("cobalt" in item for item in body["input"]):
                raise urllib.error.HTTPError(url, 422, "input rejected", None, None)
            return accepted(url, body, headers, **kwargs)

        self.egress.side_effect = post
        restarted = self.provider("atlas", **settings)
        deadline = time.monotonic() + 3
        while restarted._store.stats()["vectors"] != 1:
            self.assertLess(time.monotonic(), deadline, "healthy capture never received a vector")
            time.sleep(0.01)
        self.assertTrue(restarted._store.recall("cobalt", lexical_only=True))
        self.assertEqual(len(restarted._store.pending_embeddings(indexer.owner)), 1)
        for call in self.egress.call_args_list:
            self.assertEqual(call.args[0], "https://atlas.invalid/v1/embeddings")
            self.assertEqual(call.args[2]["Authorization"], "Bearer fixture-atlas-key")
        restarted.shutdown()

        self.egress.side_effect = accepted
        recovered = self.provider("atlas", **settings)
        deadline = time.monotonic() + 3
        while recovered._store.stats()["vectors"] != 2:
            self.assertLess(time.monotonic(), deadline, "rejected capture never retried")
            time.sleep(0.01)
        self.assertEqual(recovered._store.pending_embeddings(indexer.owner), [])


class HermesEmbeddingTransportTests(unittest.TestCase):
    def test_redirects_are_never_followed(self):
        request = urllib.request.Request("https://origin.invalid/embeddings",
                                         headers={"Authorization": "Bearer synthetic"})
        with self.assertRaises(urllib.error.HTTPError):
            embed._NoRedirect().redirect_request(request, None, 302, "", {}, "https://target.invalid")

    def test_loopback_ignores_ambient_proxy_without_touching_env(self):
        with patch("urllib.request.build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b"{}"
            embed._post("http://localhost:11434/api/embed", {}, timeout=3, no_redirect=True)
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler) and not h.proxies
                            for h in build.call_args.args))
