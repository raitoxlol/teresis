import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from teresis import MemoryStore
from teresis.extract import extract
from teresis.hermes import TeresisMemoryProvider, install
from teresis.http import make_handler
from teresis.mcp import Server
from teresis.secrets import contains_secret, redact_secrets


class ExtractTests(unittest.TestCase):
    def test_extracts_preferences_rules_decisions(self):
        text = ("I prefer pnpm over npm. Can you fix the build? We decided to use SSE for live updates.\n"
                "Never force-push to main. What if we used Redis?")
        got = {(c.kind, c.content) for c in extract(text)}
        self.assertIn(("preference", "I prefer pnpm over npm."), got)
        self.assertIn(("decision", "We decided to use SSE for live updates."), got)
        self.assertIn(("procedure", "Never force-push to main."), got)
        self.assertEqual(len(got), 3)  # questions skipped

    def test_strips_remember_this_for_later_lead_in(self):
        got = extract("Remember this for later: my home wifi network is called EmberNet-53.")
        self.assertEqual([c.content for c in got], ["my home wifi network is called EmberNet-53."])

    def test_strips_update_lead_in(self):
        got = extract("Update: I prefer spaces now.")
        self.assertEqual([c.content for c in got], ["I prefer spaces now."])

    def test_splits_compound_sentence_and_strips_lead_in(self):
        text = ("For future reference: my deploy rule is that we never ship on Fridays, "
                "and my staging database is called quokka-staging on port 5433.")
        got = {(c.kind, c.content) for c in extract(text)}
        self.assertEqual(got, {
            ("procedure", "my deploy rule is that we never ship on Fridays"),
            ("fact", "my staging database is called quokka-staging on port 5433."),
        })

    def test_extracts_agentic_coding_facts(self):
        text = ("We switched from npm to pnpm. Migrated the DB from MySQL to Postgres.\n"
                "Use uv instead of pip for installs. We replaced Redis with Valkey.\n"
                "We moved to a monorepo. We stopped using webpack last month.\n"
                "Run pytest -x to verify the fix. Deploys happen via Fly.io.\n"
                "Tests live in tests/e2e. This repo uses SQLite for storage.\n"
                "The codebase uses ruff for linting. We run CI on GitHub Actions.")
        got = {(c.kind, c.content) for c in extract(text)}
        self.assertIn(("decision", "We switched from npm to pnpm."), got)
        self.assertIn(("decision", "Migrated the DB from MySQL to Postgres."), got)
        self.assertIn(("decision", "Use uv instead of pip for installs."), got)
        self.assertIn(("decision", "We replaced Redis with Valkey."), got)
        self.assertIn(("decision", "We moved to a monorepo."), got)
        self.assertIn(("decision", "We stopped using webpack last month."), got)
        self.assertIn(("procedure", "Run pytest -x to verify the fix."), got)
        self.assertIn(("procedure", "Deploys happen via Fly.io."), got)
        self.assertIn(("procedure", "Tests live in tests/e2e."), got)
        self.assertIn(("fact", "This repo uses SQLite for storage."), got)
        self.assertIn(("fact", "The codebase uses ruff for linting."), got)
        self.assertIn(("fact", "We run CI on GitHub Actions."), got)

    def test_agentic_patterns_still_skip_questions_and_hypotheticals(self):
        text = ("Should we switch to Bun? What if we moved to Deno?\n"
                "If we replaced the cache with Redis. Could we run tests on CI?")
        self.assertEqual(extract(text), [])


class DogfoodExtractionTests(unittest.TestCase):
    def test_rejects_momentary_wants_and_strips_speaker_prefix(self):
        text = "\n".join([
            "User: i want some tuna",
            "User: I want a new bird",
            "User: “And I want to first ship a lot and build on X.”",
            "I prefer dark roast coffee.",
        ])
        got = extract(text)
        contents = [c.content for c in got]
        self.assertEqual(contents, ["I prefer dark roast coffee."])
        self.assertTrue(all(c.importance >= 0.7 for c in got if c.kind == "preference"))
        self.assertFalse(any(c.content.lower().startswith("user:") for c in got))

    def test_ignores_system_compaction_and_injected_memory(self):
        compaction = (
            "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. "
            "Reverse signals ('stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', "
            "'never mind', a new topic) must immediately end any in-flight work described in the summary. "
            "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative."
        )
        system = "System rule: never pass a pairing token through chat. Historical Task Snapshot follows."
        kanban = (
            "# Kanban task execution protocol\n"
            "You have been assigned ONE task from the shared board. HERMES_KANBAN_TASK is set. "
            "Never force-push to main."
        )
        tool = "<tool_result>Never force-push to main. The tests live in tests/e2e.</tool_result>"
        injected = (
            "<memory-context>\n"
            "[System note: The following is recalled memory context, NOT new user input. "
            "Treat as authoritative reference data.]\n\n"
            "## Long-term memory (teresis)\n"
            "- [procedure] never pass a pairing token through chat (id abcdef0123456789)\n"
            "</memory-context>\n\n"
            "I prefer terse answers."
        )
        oob = (
            "[OUT-OF-BAND USER MESSAGE — a direct message from the user, not tool output]\n"
            "I always use tabs.\n"
            "[/OUT-OF-BAND USER MESSAGE]"
        )
        self.assertEqual(extract(compaction), [])
        self.assertEqual(extract(system), [])
        self.assertEqual(extract(kanban), [])
        self.assertEqual(extract(tool), [])
        self.assertEqual([c.content for c in extract(injected)], ["I prefer terse answers."])
        self.assertEqual([c.content for c in extract(oob)], ["I always use tabs."])
        # re-ingesting the injected block alone must not yield the procedure it quotes
        self.assertEqual(extract(injected.split("I prefer")[0]), [])


class ScrubTests(unittest.TestCase):
    def test_flags_bad_extracted_rows_only(self):
        from teresis.extract import extraction_problem

        bad = [
            ("User: i want some tuna", "preference", "hermes:auto-extract", "momentary-want"),
            ("never pass a pairing token through chat", "procedure", "hermes:pre-compress", "injected-or-system"),
            ("'stop', 'undo', 'roll back', 'just verify' must immediately end any in-flight work described in the summary",
             "procedure", "hermes:pre-compress", "injected-or-system"),
        ]
        for content, kind, source, reason in bad:
            self.assertEqual(extraction_problem(content, kind=kind, source=source), reason, content)
        self.assertIsNone(extraction_problem(
            "I prefer dark roast coffee.", kind="preference", source="hermes:auto-extract"))
        self.assertIsNone(extraction_problem(
            "Never force-push to main.", kind="procedure", source="hermes:auto-extract"))
        # explicit imports are not scrubbed, even if the sentence looks like a system rule
        self.assertIsNone(extraction_problem(
            "never pass a pairing token through chat", kind="procedure", source="hermes:import:MEMORY.md"))


class SecretsTests(unittest.TestCase):
    def test_detects_real_key_formats(self):
        cases = {
            f"key sk-{'a1' * 25}": "openai_key",
            f"key sk-ant-{'b2' * 25}": "anthropic_key",
            f"pat ghp_{'Q7' * 20}": "github_token",
            f"pat github_pat_{'Ab1_' * 11}": "github_token",
            f"aws AKIA{'B' * 16}": "aws_access_key",
            f"slack xoxb-{'9' * 11}-{'a' * 12}": "slack_token",
            f"hf hf_{'xY4' * 10}": "huggingface_token",
            f"re re_{'z9' * 15}": "resend_key",
            f"stripe sk_live_{'q' * 24}": "stripe_key",
            f"auth Bearer {'T' * 40}": "bearer_token",
            f"jwt eyJ{'a' * 12}.eyJ{'b' * 12}.{'c' * 16}": "bearer_token",
            f"OPENAI_API_KEY={'x1' * 20}": "env_secret",
            f"DB_PASSWORD: {'p9' * 20}": "env_secret",
            '{"api_key": "' + 'ab12cd34' * 3 + '"}': "env_secret",
            f"dsn postgres://u:{'sekrit9' * 2}@h/db": "uri_credential",
            "-----BEGIN EC PRIVATE KEY-----\nabc123\n-----END EC PRIVATE KEY-----": "private_key",
        }
        for text, want in cases.items():
            self.assertEqual(contains_secret(text), want, text)

    def test_ignores_placeholders_and_ordinary_text(self):
        clean = [
            "Service port is 4000",
            "docs at https://example.com/docs/page.html",
            "DB url postgres://localhost:5432/appdb",
            "git remote ssh://git@github.com/org/repo.git",
            "commit a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "uuid 9b2e4c5a-1234-5678-9abc-def012345678",
            "API_KEY=your-api-key-here",
            "TOKEN=$HOME",
            "SECRET=<your-secret>",
            "PASSWORD=xxx",
            "the secret to good pasta is salt",
            "the monkey keyboard tokenizer session",
            "Never commit secrets",
            "We switched from npm to pnpm",
            "password=correct horse battery staple",
            "remember to rotate the key=soon please",
        ]
        for t in clean:
            self.assertIsNone(contains_secret(t), t)

    def test_documentation_key_shaped_values_are_redacted(self):
        out, kinds = redact_secrets("AWS docs show AKIAIOSFODNN7EXAMPLE as an example")
        self.assertEqual(out, "AWS docs show [REDACTED:aws_access_key] as an example")
        self.assertEqual(kinds, ["aws_access_key"])

    def test_redact_replaces_only_the_secret_span(self):
        text, kinds = redact_secrets(
            f"Deploy uses OPENAI_API_KEY=sk-{'a1' * 25} and db postgres://u:{'sekrit9' * 2}@h/db")
        self.assertEqual(kinds, ["openai_key", "uri_credential"])
        self.assertIn("OPENAI_API_KEY=[REDACTED:openai_key]", text)
        self.assertIn("postgres://u:[REDACTED:uri_credential]@h/db", text)
        self.assertIn("Deploy uses", text)
        self.assertIsNone(contains_secret(text))  # nothing left to flag

    def test_redact_reports_each_kind_once(self):
        _, kinds = redact_secrets(f"a sk-{'a1' * 25} b sk-{'c2' * 25}")
        self.assertEqual(kinds, ["openai_key"])


class StoreExtrasTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.s = MemoryStore(Path(self.d.name) / "m.db", embedder=None)

    def tearDown(self):
        self.s.close()
        self.d.cleanup()

    def test_feedback(self):
        m = self.s.remember("Deploys use Fly.io", scope="p", importance=0.15)
        self.assertAlmostEqual(self.s.feedback(m.id, True)["importance"], 0.25)
        r = self.s.feedback(m.id, False)
        r = self.s.feedback(m.id, False)
        self.assertTrue(r["flagged"])

    def test_conflicts(self):
        self.s.remember("The user's code editor is VS Code", scope="user")
        self.s.remember("The user's code editor is Neovim", scope="user")
        self.s.remember("Backups run nightly via restic", scope="user")
        pairs = self.s.conflicts("user")
        self.assertEqual(len(pairs), 1)
        self.assertIn("Neovim", pairs[0]["newer"]["content"])

    def test_tuned_weight_defaults(self):
        from teresis import Weights
        w = Weights()
        self.assertEqual(w.vector, 2.0)
        self.assertEqual(w.min_cosine, 0.0)
        self.assertEqual(w.mmr, 0.0)

    def test_mmr_diversifies(self):
        from teresis import Weights
        for i in range(4):
            self.s.remember(f"Deploy pipeline step {i}: deploy pipeline builds the image", scope="p")
        other = self.s.remember("The deploy pipeline also posts release notes to the shared channel", scope="p")
        plain = [m.id for m in self.s.recall("deploy pipeline", scope="p", k=3, touch=False)]
        self.s.w = Weights(mmr=0.6)
        diverse = [m.id for m in self.s.recall("deploy pipeline", scope="p", k=3, touch=False)]
        self.assertNotIn(other.id, plain)  # near-copies crowd it out without MMR
        self.assertIn(other.id, diverse)

    def test_find_and_exclude_kinds(self):
        self.s.remember("Talked about deploy pipeline", scope="p", kind="episode")
        f = self.s.remember("Deploy pipeline uses GitHub Actions", scope="p")
        self.assertEqual(self.s.find("deploy pipeline uses github actions!", scope="p").id, f.id)
        hits = self.s.recall("deploy pipeline", scope="p", exclude_kinds=["episode"])
        self.assertEqual([h.id for h in hits], [f.id])


class HermesProviderTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = str(Path(self.d.name) / "h.db")

    def tearDown(self):
        self.d.cleanup()

    def provider(self, **init):
        p = TeresisMemoryProvider(config={"db_path": self.db})
        self.assertTrue(p.is_available())
        self.addCleanup(p.shutdown)
        p.initialize("sess-1", hermes_home=self.d.name, platform="cli", agent_identity="max", **init)
        return p

    def test_near_duplicate_writes_are_skipped_but_changes_are_kept(self):
        p = self.provider()
        p.on_memory_write("add", "memory", "Alice's staging database is named quokka-staging and uses port 5433.")
        # extractor path, different wording, same fact -> skipped
        p.sync_turn("my staging database is called quokka-staging on port 5433.", "ok")
        hits = [m for m in p._store.recall("staging database port", scope=p._read_scopes, k=10,
                                           exclude_kinds=["episode"])]
        self.assertEqual(len(hits), 1)
        # a changed port supersedes the old value in place; history keeps it
        p.sync_turn("my staging database is called quokka-staging on port 6000.", "ok")
        hits = p._store.recall("staging database port", scope=p._read_scopes, k=10, exclude_kinds=["episode"])
        self.assertEqual(len(hits), 1)
        self.assertIn("6000", hits[0].content)
        self.assertNotIn("5433", hits[0].content)
        # a different service on the same port is a separate fact
        p.sync_turn("my prod database is called quokka-prod on port 6000.", "ok")
        hits = p._store.recall("database port", scope=p._read_scopes, k=10, exclude_kinds=["episode"])
        self.assertEqual(len(hits), 2)
        # flipped polarity is kept too
        p.sync_turn("we never ship on Fridays.", "ok")
        p.sync_turn("we always ship on Fridays.", "ok")
        hits = p._store.recall("ship on Fridays", scope=p._read_scopes, k=10, exclude_kinds=["episode"])
        self.assertEqual(len(hits), 2)

    def test_embedder_settings_come_from_config(self):
        import os
        for v in ("TERESIS_EMBED", "TERESIS_EMBED_MODEL"):
            os.environ.pop(v, None)
        self.addCleanup(lambda: [os.environ.pop(v, None) for v in ("TERESIS_EMBED", "TERESIS_EMBED_MODEL", "TERESIS_EMBED_URL")])
        p = TeresisMemoryProvider(config={"db_path": self.db, "embed": "ollama", "embed_model": "all-minilm"})
        self.addCleanup(p.shutdown)
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="max")
        self.assertIsNotNone(p._store.embedder)

    def test_full_lifecycle(self):
        p = self.provider()
        self.assertIn("hermes/max", p.system_prompt_block())
        names = {t["name"] for t in p.get_tool_schemas()}
        self.assertIn("memory_remember", names)
        self.assertTrue(all("parameters" in t for t in p.get_tool_schemas()))

        out = json.loads(p.handle_tool_call("memory_remember", {"content": "Atlas uses PostgreSQL 16", "key": "atlas.db"}))
        self.assertTrue(out["result"].startswith("created"))
        p.sync_turn("I prefer terse answers without apologies. Please fix the Atlas migration.",
                    "Fixed the migration in 0042.", session_id="sess-1")
        p.on_memory_write("add", "user", "User lives in Tokyo")
        p.on_memory_write("replace", "user", "User lives in Osaka", {"previous_content": "User lives in Tokyo"})

        ctx = p.prefetch("where does the user live and how should I answer")
        self.assertIn("Osaka", ctx)
        self.assertNotIn("Tokyo", ctx)
        self.assertIn("terse answers", ctx)
        ctx = p.prefetch("atlas migration database")
        self.assertIn("PostgreSQL", ctx)
        self.assertIn("Related past conversation", ctx)
        self.assertEqual(p.prefetch("ok"), "")

        p.on_memory_write("remove", "user", "User lives in Osaka", {"previous_content": "User lives in Osaka"})
        self.assertNotIn("Osaka", p.prefetch("where does the user live"))
        self.assertIn("Saved to long-term memory",
                      p.on_pre_compress([{"role": "user", "content": "We decided to ship on Thursdays."}]))
        p.on_delegation("audit deps", "2 outdated packages", child_session_id="c1")
        p.shutdown()

    def test_rerank_config_schema_and_fallback(self):
        import os
        old = {v: os.environ.get(v) for v in ("TERESIS_RERANK", "TERESIS_RERANK_MODEL")}

        def restore():
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)

        schema = {e["key"]: e for e in TeresisMemoryProvider().get_config_schema()}
        self.assertIn("rerank", schema)
        self.assertIn("rerank_model", schema)
        self.assertEqual(schema["rerank_model"]["default"], "Xenova/ms-marco-MiniLM-L-6-v2")

        # an unknown reranker warns and disables; initialize() must never crash
        p = TeresisMemoryProvider(config={"db_path": self.db, "rerank": "bogus-backend"})
        p.initialize("s", hermes_home=self.d.name, platform="cli", agent_identity="max")
        self.assertIsNone(p._store.reranker)
        p.shutdown()

        # a fastembed config initializes cleanly whether or not fastembed is installed
        p2 = TeresisMemoryProvider(
            config={"db_path": str(Path(self.d.name) / "h2.db"), "rerank": "fastembed"})
        p2.initialize("s2", hermes_home=self.d.name, platform="cli", agent_identity="max")
        try:
            import fastembed  # noqa: F401
        except Exception:
            self.assertIsNone(p2._store.reranker)
        else:
            self.assertIsNotNone(p2._store.reranker)
        self.assertIsNotNone(p2._store)
        p2.shutdown()

    def test_writes_are_scrubbed_of_secrets(self):
        p = self.provider()
        ghp = "ghp_" + "Q7" * 20
        sk = "sk-" + "a1" * 25
        env = "h7" * 20
        p.on_memory_write("add", "memory", f"The gateway token is {ghp}.")
        p.sync_turn(f"my api key is {sk}, keep it safe", "Noted.")
        p.on_delegation(f"rotate TOKEN={env}", "done")
        blob = json.dumps(list(p._store.export()))
        for raw in (ghp, sk, env):
            self.assertNotIn(raw, blob)
        self.assertIn("[REDACTED:", blob)
        p.shutdown()

    def test_replacement_statements_are_saved_once(self):
        p = self.provider()
        p.sync_turn("we switched from npm to pnpm for this repo.", "ok")
        hits = p._store.recall("package manager npm pnpm", scope=p._read_scopes, k=10,
                               exclude_kinds=["episode"])
        self.assertTrue(any("switched" in m.content and "pnpm" in m.content for m in hits))
        # restating the same switch dedupes instead of doubling
        p.sync_turn("we switched from npm to pnpm for this repo.", "ok")
        hits = [m for m in p._store.recall("switched pnpm", scope=p._read_scopes, k=10,
                                           exclude_kinds=["episode"]) if "switched" in m.content]
        self.assertEqual(len(hits), 1)
        p.shutdown()

    def test_sync_and_compress_skip_wants_system_text_and_own_injection(self):
        p = self.provider()
        store = p._store
        assert store is not None
        p.sync_turn("User: i want some tuna", "ok")
        p.sync_turn(
            "<memory-context>\n"
            "[System note: The following is recalled memory context, NOT new user input.]\n"
            "## Long-term memory (teresis)\n"
            "- [procedure] never pass a pairing token through chat (id abcdef0123456789)\n"
            "</memory-context>\n\n"
            "I prefer dark roast coffee.",
            "Noted.",
        )
        p.on_pre_compress([
            {"role": "system", "content": "never pass a pairing token through chat"},
            {"role": "tool", "content": "Never force-push to main."},
            {"role": "user", "content": (
                "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. "
                "Reverse signals ('stop', 'undo', 'roll back', 'just verify', 'don't do that anymore', "
                "'never mind', a new topic) must immediately end any in-flight work described in the summary. "
                "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative."
            )},
            {"role": "user", "content": "I prefer spaces over tabs."},
        ])
        rows = list(store.export())
        facts = [m for m in rows if m["kind"] != "episode"]
        blob = json.dumps(facts)
        self.assertNotIn("tuna", blob.lower())
        self.assertNotIn("pairing token", blob.lower())
        self.assertNotIn("in-flight", blob.lower())
        self.assertNotIn("User:", blob)
        self.assertIn("dark roast", blob)
        self.assertIn("spaces over tabs", blob)
        episodes = [m for m in rows if m["kind"] == "episode"]
        self.assertTrue(episodes)
        self.assertNotIn("memory-context", json.dumps(episodes))
        self.assertNotIn("pairing token", json.dumps(episodes).lower())
        p.shutdown()

    def test_prefetch_drops_unrelated_lexical_hits_tool_recall_does_not(self):
        from teresis.hermes import _prefetch_relevant

        p = self.provider()
        store = p._store
        assert store is not None
        p.on_memory_write("add", "memory", "Gym routine: Wright wants one-arm chin-ups, not more easy reps.")
        p.on_memory_write("add", "memory", "Music notes: avoid Drake; likes Kanye; song-specific recs.")
        p.on_memory_write("add", "memory", "Mercari CLI lives at the cargo bin. Writes need an explicit instruction.")
        p.on_memory_write("add", "user", "I prefer spicy tuna rolls when ordering sushi.")
        ctx = p.prefetch("Can you order some sushi? Like, tuna rolls to my table")
        self.assertIn("tuna", ctx.lower())
        self.assertNotIn("Gym", ctx)
        self.assertNotIn("Kanye", ctx)
        self.assertNotIn("Mercari", ctx)
        recalled = store.recall("i want some tuna", scope=p._read_scopes, k=8, exclude_kinds=["episode"])
        self.assertTrue(any("Gym" in m.content for m in recalled))
        self.assertNotIn("Gym", p.prefetch("i want some tuna"))
        self.assertFalse(_prefetch_relevant("i want some tuna", "Gym routine: Wright wants one-arm chin-ups", floor=0.15, score=0.9))
        self.assertFalse(_prefetch_relevant("tuna rolls", "spicy tuna rolls", floor=0.45, score=0.2))
        self.assertTrue(_prefetch_relevant("tuna rolls", "spicy tuna rolls", floor=0.45, score=0.8))
        p.shutdown()

    def test_scrub_command_is_dry_run_until_apply(self):
        from teresis.cli import main

        p = self.provider()
        store = p._store
        assert store is not None
        store.remember("User: i want some tuna", kind="preference", source="hermes:auto-extract", importance=0.6)
        store.remember("I prefer dark roast coffee.", kind="preference", source="hermes:auto-extract", importance=0.8)
        p.shutdown()
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--db", self.db, "scrub"]), 0)
        still = MemoryStore(self.db, embedder=None)
        self.addCleanup(still.close)
        contents = [m["content"] for m in still.export() if not m.get("deleted_at")]
        self.assertIn("User: i want some tuna", contents)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--db", self.db, "scrub", "--apply"]), 0)
        contents = [m["content"] for m in still.export() if not m.get("deleted_at")]
        self.assertNotIn("User: i want some tuna", contents)
        self.assertIn("I prefer dark roast coffee.", contents)

    def test_subagent_is_read_only(self):
        p = self.provider(agent_context="subagent")
        out = json.loads(p.handle_tool_call("memory_remember", {"content": "should not save"}))
        self.assertIn("error", out)
        p.sync_turn("I prefer tabs", "ok")
        self.assertIn("No memories", json.loads(p.handle_tool_call("memory_recall", {"query": "tabs"}))["result"])
        p.shutdown()

    def test_install_layout(self):
        dest = install(self.d.name)
        init = (dest / "__init__.py").read_text()
        self.assertIn("register_memory_provider", init)
        self.assertTrue((dest / "teresis" / "hermes.py").exists())
        self.assertTrue((dest / "plugin.yaml").exists())
        dest = install(self.d.name, link=True)  # re-install over a copy
        self.assertTrue((dest / "teresis").is_symlink())


class HttpTests(unittest.TestCase):
    def test_http_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = MemoryStore(Path(d) / "m.db", embedder=None)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Server(store, "project/x"), "tok"))
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"

            def call(path, body=None, token="tok"):
                req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                             headers={"Authorization": f"Bearer {token}"})
                try:
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    with e:
                        return e.code, json.loads(e.read())

            self.assertEqual(call("/health")[0], 200)
            self.assertEqual(call("/health", token="bad")[0], 401)
            self.assertEqual(call("/tools/memory_remember", {"content": "Port is 4000"})[0], 200)
            code, body = call("/tools/memory_recall", {"query": "port"})
            self.assertEqual(code, 200)
            self.assertEqual(body["memories"][0]["content"], "Port is 4000")
            self.assertEqual(call("/tools/nope", {})[0], 404)
            self.assertEqual(call("/tools/memory_update", {"id": "missing", "content": "x"})[0], 400)
            httpd.shutdown()
            httpd.server_close()
            store.close()

    def test_hermes_import_memories(self):
        from teresis.hermes import import_memories

        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "profiles" / "max"
            (home / "memories").mkdir(parents=True)
            dbp = home / "teresis.db"
            (home / "config.yaml").write_text(
                f"plugins:\n  teresis:\n    db_path: {dbp}\n    scope: hermes/max\n"
            )
            (home / "memories" / "MEMORY.md").write_text(
                "Vault is canonical source.\n§\nDeploy uses sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456.\n"
            )
            (home / "memories" / "USER.md").write_text(
                "Prefers Neovim.\n§\nAvoids Drake; likes Kanye.\n"
            )
            dry = import_memories(home, dry_run=True)
            self.assertEqual((dry["memory_entries"], dry["user_entries"], dry["created"]), (2, 2, 0))
            self.assertFalse(dbp.exists())

            first = import_memories(home)
            self.assertEqual((first["created"], first["duplicates"], first["redacted"]), (4, 0, 1))
            self.assertEqual(first["scope"], "hermes/max")

            second = import_memories(home)
            self.assertEqual((second["created"], second["duplicates"]), (0, 4))

            with MemoryStore(dbp, embedder=None, reranker=None) as s:
                hits = s.recall("Neovim", scope=["hermes/max", "user"])
                self.assertTrue(any("Neovim" in h.content for h in hits))
                all_text = " ".join(m["content"] for m in s.export())
                self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456", all_text)

    def test_cli_db_and_json_after_subcommand(self):
        import io
        from contextlib import redirect_stdout
        from teresis.cli import main as cli_main

        with tempfile.TemporaryDirectory() as d:
            dbp = str(Path(d) / "cli.db")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(["remember", "Atlas uses Postgres", "--db", dbp, "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["status"], "created")

            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc = cli_main(["stats", "--db", dbp, "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf2.getvalue())["active"], 1)


if __name__ == "__main__":
    unittest.main()
