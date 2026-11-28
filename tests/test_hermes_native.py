"""Run against a Hermes checkout using HERMES_NATIVE_SOURCE and its Python environment."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "teresis"
FIRST = "For future reference, I prefer using the cobalt terminal."
SECOND = "For future reference, we always label backups with juniper."


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _active_candidates(provider):
    return [r for r in provider._store.export()
            if r.get("kind") == "candidate" and not r.get("deleted_at")]


def _exercise_review(manager, provider):
    """Receipts and human-in-chat review driven through MemoryManager, not the provider."""
    tools = {s["name"] for s in manager.get_all_tool_schemas()}
    assert {"memory_why", "memory_review"} <= tools, tools

    provider._store.remember("The Kestrel worker listens on port 6600", scope=provider._scope,
                             kind="fact", meta={"origin": "user-typed", "trust": "human"})
    # Human turns without a strong marker: the extractor quarantines both as candidates.
    # sync_all is queued on the manager's background worker, so poll the store.
    manager.sync_all("My database port is 5432.", "Understood.")
    manager.sync_all("We run Postgres on staging.", "Understood.")
    assert _wait_for(lambda: len(_active_candidates(provider)) >= 2), _active_candidates(provider)
    candidates = _active_candidates(provider)
    assert len(candidates) == 2, candidates

    query = "what port does the kestrel worker listen on"
    manager.on_turn_start(1, query, author_id=None, author_name=None, author_is_bot=False)
    text = manager.prefetch_all(query, session_id="native-review")
    assert "6600" in text, text
    # Candidates are never injected: the packet holds the fact and episodes, not their ids.
    for row in candidates:
        assert row["id"] not in text and row["id"] not in provider._last_ids, (row, text)

    out = json.loads(manager.handle_tool_call("memory_why", {}))
    assert "This turn" in out["result"] and "you said this" in out["result"], out

    listed = json.loads(manager.handle_tool_call("memory_review", {}))
    assert listed["waiting"] == 2 and len(listed["items"]) == 2, listed

    # The model cannot approve: extra args are ignored, both rows stay candidates.
    manager.handle_tool_call("memory_review", {"keep": [1, 2], "action": "promote"})
    for item in listed["items"]:
        assert provider._store.get(item["id"]).kind == "candidate", item

    # The user's own reply applies: item 1 is promoted, item 2 still waits.
    manager.on_turn_start(2, "keep 1", author_id=None, author_name=None, author_is_bot=False)
    text = manager.prefetch_all("keep 1", session_id="native-review")
    first, second = listed["items"][0]["id"], listed["items"][1]["id"]
    kept = provider._store.get(first)
    assert kept.kind != "candidate" and kept.meta.get("promoted_by") == "chat-review", kept.to_dict()
    assert provider._store.get(second).kind == "candidate"
    assert "Memory review" in text, text


def exercise_provider(phase):
    from agent.memory_manager import MemoryManager
    from plugins.memory import load_memory_provider

    manager = MemoryManager()
    provider = load_memory_provider("teresis", register_skills=False)
    assert provider is not None, "Hermes did not load Teresis"
    manager.add_provider(provider)
    # Hermes' agent passes platform (platform or "cli") so the provider's trust gate can
    # attribute the turn; without it the platform is "" and nothing counts as human-typed.
    manager.initialize_all("native-review" if phase == "review" else "native-test", platform="cli")
    try:
        if phase != "restart":
            manager.sync_all(FIRST, "Understood.")
            manager.sync_all(SECOND, "Understood.")
            if phase == "capture":
                deadline = time.monotonic() + 5
                while not Path("embedding-started").exists():
                    assert time.monotonic() < deadline, "no embedding request started"
                    time.sleep(0.01)
            elif phase == "review":
                _exercise_review(manager, provider)
        else:
            # Verify lexical recall before the delayed index completes, without a query embed.
            for word in ("cobalt", "juniper"):
                assert provider._store.recall(word, lexical_only=True, kinds=["episode"]), word
            assert provider._store.recall("cobalt", lexical_only=True, kinds=["preference"])
            deadline = time.monotonic() + 5
            while provider._store.pending_embeddings(provider._capture_indexer.owner):
                assert time.monotonic() < deadline, "pending embedding work did not resume"
                time.sleep(0.05)
            hits = json.loads(provider.handle_tool_call("memory_recall", {"query": "xqzv91", "k": 20}))
            episodes = [hit["content"] for hit in hits["memories"] if hit["kind"] == "episode"]
            assert any("cobalt" in text for text in episodes), hits
            assert any("juniper" in text for text in episodes), hits
    finally:
        manager.shutdown_all()
    assert manager.shutdown_drain_state["status"] == "drained", manager.shutdown_drain_state
    if phase == "lexical":
        provider = load_memory_provider("teresis", register_skills=False)
        provider.initialize("lexical-restart")
        try:
            for word in ("cobalt", "juniper"):
                assert provider._store.recall(word, kinds=["episode"]), word
            assert provider._store.stats()["vectors"] == 0
        finally:
            provider.shutdown()


@unittest.skipUnless(os.environ.get("HERMES_NATIVE_SOURCE"), "requires a Hermes checkout")
class HermesNativeCaptureTests(unittest.TestCase):
    def test_slow_index_does_not_hold_capture_drain_and_restart_retries_it(self):
        delay = threading.Event()
        requests = []
        self.addCleanup(delay.set)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                inputs = payload["input"]
                requests.append(inputs)
                (root / "semantic" / "embedding-started").touch()
                delay.wait(6.5)
                body = json.dumps({"embeddings": [[1, 0] for _ in inputs]}).encode()
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def run(phase, *, lexical=False):
                    home = root / ("lexical" if lexical else "semantic")
                    plugin = home / "plugins" / "teresis"
                    if not plugin.exists():
                        shutil.copytree(PACKAGE, plugin, ignore=shutil.ignore_patterns("__pycache__"))
                    config = "memory:\n  provider: teresis\nplugins:\n  teresis:\n    db_path: '$HERMES_HOME/memory.db'\n"
                    if not lexical:
                        config += (f"    embed: ollama\n    embed_model: synthetic\n    embed_timeout: 12\n"
                                   f"    embed_url: http://127.0.0.1:{server.server_port}\n")
                    (home / "config.yaml").write_text(config)
                    env = {**os.environ, "HERMES_HOME": str(home),
                           "PYTHONPATH": os.environ["HERMES_NATIVE_SOURCE"]}
                    result = subprocess.run([sys.executable, __file__, phase], cwd=home, env=env,
                                            capture_output=True, text=True, timeout=16)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                run("capture")
                delay.set()
                run("restart")
                self.assertTrue(any("xqzv91" in batch for batch in requests))
                total = len(requests)
                run("lexical", lexical=True)
                self.assertEqual(len(requests), total)
            finally:
                delay.set()
                server.shutdown()
                thread.join()

    def test_review_in_chat(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        home = Path(directory.name) / "review"
        plugin = home / "plugins" / "teresis"
        shutil.copytree(PACKAGE, plugin, ignore=shutil.ignore_patterns("__pycache__"))
        (home / "config.yaml").write_text(
            "memory:\n  provider: teresis\nplugins:\n  teresis:\n    db_path: '$HERMES_HOME/memory.db'\n")
        env = {**os.environ, "HERMES_HOME": str(home),
               "PYTHONPATH": os.environ["HERMES_NATIVE_SOURCE"]}
        result = subprocess.run([sys.executable, __file__, "review"], cwd=home, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    exercise_provider(sys.argv[1])
