"""Focused integration tests for the Hermes evidence-packet prefetch prototype.

These tests build synthetic in-memory stores and drive ``TeresisMemoryProvider.prefetch``
directly. No Hermes profile, embedder, or network call is involved.
"""

import re
import unittest
from unittest.mock import patch

from teresis.hermes import TeresisMemoryProvider
from teresis.text import estimate_tokens

SCOPE = "hermes/replay"
ASK = "Is the billing service owner available?"

_ID = re.compile(r"\(id ([0-9a-f]{16})(?:; linked from [0-9a-f]{16})?\)")
_LINKED = re.compile(r"\(id ([0-9a-f]{16}); linked from ([0-9a-f]{16})\)")


class PacketTests(unittest.TestCase):
    def provider(self, **settings):
        config = {"db_path": ":memory:", "scope": SCOPE, "extra_scopes": "",
                  "embed": "", "rerank": "", **settings}
        p = TeresisMemoryProvider(config)
        self.addCleanup(p.shutdown)
        p.initialize("synthetic", platform="cli")
        return p

    def remember(self, p, content, *, scope=SCOPE, kind="fact", key=None,
                 source="hermes:memory-tool", ttl_days=None, meta=None, importance=0.5):
        return p._store.remember(content, scope=scope, kind=kind, key=key,
                                 source=source, ttl_days=ttl_days, meta=meta,
                                 importance=importance).id

    def ids(self, text):
        return _ID.findall(text)

    # -- linked retrieval -------------------------------------------------
    def test_two_hop_billing_owner_links_leave_and_cites_anchor(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertIn(leave, text)
        links = _LINKED.findall(text)
        self.assertEqual(links, [(leave, owner)])
        self.assertIn("## Related facts (shared entity)", text)
        self.assertEqual(p._last_count, len(self.ids(text)))

    def test_linked_disabled_by_default_returns_direct_fact_only(self):
        p = self.provider()
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertNotIn(leave, text)
        self.assertNotIn("linked from", text)

    def test_linked_sibling_scope_is_not_bridged(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.", scope="hermes/other")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertNotIn(leave, text)
        self.assertNotIn("linked from", text)

    def test_linked_ambiguous_hub_is_skipped(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.")
        hobby = self.remember(p, "Priya collects vintage fountain pens.")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        # Three facts share the entity "Priya": the link is ambiguous, so no peer.
        self.assertNotIn("linked from", text)
        self.assertNotIn(hobby, text)

    def test_linked_expired_peer_is_skipped(self):
        p = self.provider(prefetch_linked=True)
        store = p._store
        store.clock = lambda: 1_700_000_000.0
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.", ttl_days=1)
        store.clock = lambda: 1_700_000_000.0 + 2 * 86400
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertNotIn(leave, text)
        self.assertNotIn("linked from", text)

    def test_linked_untrusted_peer_is_skipped(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.")
        leave = self.remember(p, "Priya is on leave through October.",
                              source="hermes:auto-extract")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertNotIn(leave, text)
        self.assertNotIn("linked from", text)

    def test_linked_untrusted_anchor_is_not_admitted(self):
        p = self.provider(prefetch_linked=True)
        owner = self.remember(p, "Priya owns the billing service.", source="hermes:auto-extract")
        leave = self.remember(p, "Priya is on leave through October.")
        text = p.prefetch("Priya billing leave")
        self.assertNotIn(owner, text)
        self.assertIn(leave, text)
        self.assertNotIn("linked from", text)

    # -- explicit recall is unchanged ------------------------------------
    def test_explicit_recall_still_expands_entities(self):
        p = self.provider()
        store = p._store
        store.remember("Priya owns the billing service", scope=SCOPE)
        store.remember("Priya is on leave through October", scope=SCOPE)
        texts = [m.content for m in store.recall("billing service", scope=[SCOPE], k=5, touch=False)]
        self.assertIn("Priya is on leave through October", texts)

    def test_prefetch_disables_normal_entity_expansion(self):
        p = self.provider(prefetch_linked=True)
        with patch.object(p._store, "recall", wraps=p._store.recall) as spy:
            p.prefetch(ASK)
        self.assertGreaterEqual(spy.call_count, 1)
        for call in spy.call_args_list:
            self.assertFalse(call.kwargs["expand_entities"])

    # -- no passive access reinforcement ----------------------------------
    def test_prefetch_never_touches_filtered_or_admitted_rows(self):
        p = self.provider()
        admitted = self.remember(p, "Priya owns the billing service.")
        filtered = self.remember(p, "Priya is on leave through October.", source="hermes:auto-extract")
        candidate = self.remember(p, "Priya likes dark mode.", kind="candidate")
        for _ in range(2):
            p.prefetch(ASK)
        for mid in (admitted, filtered, candidate):
            m = p._store.get(mid)
            self.assertEqual(m.access_count, 0, mid)
            self.assertIsNone(m.accessed_at, mid)

    # -- zero caps ---------------------------------------------------------
    def test_zero_budget_performs_no_recall(self):
        p = self.provider(prefetch_budget_tokens=0)
        self.remember(p, "Priya owns the billing service.")
        with patch.object(p._store, "recall", wraps=p._store.recall) as spy:
            self.assertEqual(p.prefetch(ASK), "")
        spy.assert_not_called()

    def test_zero_k_performs_no_recall(self):
        p = self.provider(prefetch_k=0)
        self.remember(p, "Priya owns the billing service.")
        with patch.object(p._store, "recall", wraps=p._store.recall) as spy:
            self.assertEqual(p.prefetch(ASK), "")
        spy.assert_not_called()

    # -- budgets and packing ----------------------------------------------
    def test_budget_accounts_for_headers(self):
        p = self.provider()
        owner = self.remember(p, "Priya owns the billing service.")
        header = "## Long-term memory (teresis)\n"
        line = f"- [fact] Priya owns the billing service. (id {owner})"
        exact = estimate_tokens(header + line)
        p._config["prefetch_budget_tokens"] = exact
        self.assertEqual(p.prefetch(ASK), header + line)
        p._config["prefetch_budget_tokens"] = exact - 1
        self.assertEqual(p.prefetch(ASK), "")

    def test_oversized_hit_backfills_eligible_candidate(self):
        p = self.provider()
        store = p._store
        store.clock = lambda: 1_700_000_000.0
        small = self.remember(p, "The billing owner is on leave.")
        store.clock = lambda: 1_700_000_000.0 + 86400
        big = self.remember(p, "The billing owner manages service and " + "details " * 80,
                            importance=1.0)
        p._config["prefetch_k"] = 1
        p._config["prefetch_budget_tokens"] = 120
        text = p.prefetch("billing owner")
        self.assertIn(small, text)
        self.assertNotIn(big, text)
        self.assertLessEqual(estimate_tokens(text), 120)

    # -- episodes ----------------------------------------------------------
    def test_episodes_are_capped_at_two(self):
        p = self.provider()
        for detail in ("listens on port 4400", "writes logs to stderr", "restarts every hour"):
            self.remember(p, f"User: The Kestrel worker {detail}.\nAssistant: Noted.",
                          kind="episode", source="hermes:cli")
        text = p.prefetch("Kestrel worker")
        self.assertEqual(text.count("- [episode]"), 2)
        self.assertIn("## Related past conversation", text)

    def test_combined_k_limits_facts_and_episodes_together(self):
        p = self.provider(prefetch_k=2)
        self.remember(p, "Priya owns the billing service.")
        for detail in ("listens on port 4400", "writes logs to stderr"):
            self.remember(p, f"User: The Kestrel worker {detail}.\nAssistant: Noted.",
                          kind="episode", source="hermes:cli")
        text = p.prefetch("Priya billing Kestrel worker")
        self.assertEqual(len(self.ids(text)), 2)
        self.assertEqual(text.count("- [episode]"), 1)
        self.assertEqual(text.count("- [fact]"), 1)

    def test_episode_dedup_against_admitted_fact(self):
        p = self.provider()
        owner = self.remember(p, "Priya owns the billing service.")
        self.remember(p, "User: Priya owns the billing service.\nAssistant: Noted.",
                      kind="episode", source="hermes:cli")
        text = p.prefetch(ASK)
        self.assertIn(owner, text)
        self.assertEqual(text.count("- [episode]"), 0)
        self.assertNotIn("## Related past conversation", text)

    # -- config schema ------------------------------------------------------
    def test_config_schema_exposes_prefetch_fields(self):
        p = self.provider()
        keys = {item["key"] for item in p.get_config_schema()}
        for key in ("prefetch_k", "prefetch_budget_tokens", "prefetch_linked", "prefetch_min_score"):
            self.assertIn(key, keys)
        self.assertIs(p._config["prefetch_linked"], False)
        self.assertEqual(p._config["prefetch_budget_tokens"], 700)


if __name__ == "__main__":
    unittest.main()