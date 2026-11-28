# Teresis for Hermes: architecture decision and GA plan

Written 2026-11-25 against `main` at `751af9d` plus an uncommitted working tree. Status words:

- **code**: committed on `main`, covered by the repo's tests.
- **WIP**: in the working tree at the commit above (the packet slice), unreleased.
- **prototype**: runnable, diagnostic only. Not a feature, not evidence.
- **proposal**: nothing exists; a design to be tested.

## 1. Decision

**Principle.** Prefetch is a bounded, auditable *evidence packet* built deterministically from trusted rows.
It may be empty. Nothing generative sits in the default read or write path. *Generative extraction* models
are optional, asynchronous, proposal-only writers: what they propose reaches a packet only through the same
trust gate and review as any other candidate. Optional retrieval models (embeddings, a reranker) already
exist as opt-in read-path components and stay opt-in and off by default.

**Ambition and what it is not.** We want to beat model-free and LLM-backed memory on Hermes outcomes at a
fixed token budget: right evidence present, no stale or forbidden evidence, correct abstention, answer
correctness. That is a hypothesis to test *per named provider*, not a premise and not a gate on shipping.
Section 7 separates hard ship gates from superiority claims. Failing a superiority test is not a tie.

| Question | In GA scope | Later (gated) | No |
| --- | --- | --- | --- |
| Deterministic hybrid packet (FTS5 + trigram, trust gate, versions, hard count/token cap) | **Yes** (default) | | |
| Abstention as a first-class output | **Yes** | | |
| Stale-span overlay and current/historical intent | **Yes** (M3) | | |
| Same-scope unique entity peer (co-mention) | Experiment arm, **default off** | Default on only if M5 passes | |
| Typed relations (rule-extracted, evidence-linked) | | M6, after GA and the M5 decision | |
| Optional embeddings / local reranker | Already shipped, stays opt-in | | |
| Local-model async proposals | | Experimental, opt-in (M7, M8) | |
| Hosted inference adapter | | Maybe after M8, BYO endpoint, explicit consent | |
| Managed memory service as a dependency | | | **No** |
| Generative model call on the default read or write path | | | **No** |
| ACL-style multi-tenant isolation | | | **No** (scopes are namespaces, section 6.1) |

## 2. Where we are

### 2.1 Current code (committed)

| Area | What exists |
| --- | --- |
| Store | One SQLite file, WAL, FTS5 Porter + trigram, optional vectors, schema version 3. Keyed supersession keeps history (`superseded_by/at`), `as_of` queries, TTL, soft delete, 30-day purge in `maintain`. |
| Scopes | Path prefixes. Recall in `a/b` also reads `a` and `global`, never siblings. A namespace, not access control. |
| Write trust | Trust gate, provenance (`meta.origin`), candidate quarantine, best-effort secret redaction. |
| Read | `recall` fuses channels, applies recency/importance/reinforcement priors, one-hop **entity expansion** over untyped `memory_entities` co-mentions. `recall` writes `access_count` by default. |
| Hermes prefetch | Facts via `recall`, then up to 2 episodes. `prefetch_k=6`, `prefetch_budget_tokens=700`, distinctive-term and score floors. The committed token budget covers facts only. |
| Estimator | `estimate_tokens = ceil(chars/4)`. A heuristic, not a tokenizer. |
| Backup | `teresis export` / `import` (JSONL, ids and history preserved; vectors dropped, entities rebuilt), encrypted `teresis sync`. |
| Versions | `0.1.0` in `pyproject.toml`, `__init__.py`, `plugin.yaml`; git tag `v0.1.0`. Nothing enforces agreement. |
| CI | Unit tests on 3.10 to 3.13 and a wheel smoke test. No upgrade, restore, version-coherence or multi-Hermes-version test. |

### 2.2 WIP slice

Uncommitted in `hermes.py`, `store.py`, `evidence.py`: one `EvidencePacket` with a shared count and
estimated-token cap that includes headers, citations and episodes; `touch=False` on prefetch reads (no passive
reinforcement); order is direct facts, then at most one default-off (`prefetch_linked`) same-scope
`unique_peers` link, then eligible episodes; `expand_entities=False` for prefetch. This plan assumes the
slice lands as described and does not change it.

### 2.3 Prototype

`PYTHONPATH=src python bench/hermes_packet.py` replays 8 synthetic cases against the native provider in two
arms (direct, linked) and reports missing rows, unnecessary rows and estimated tokens against a stated budget.
It is **diagnostic only: author-written, 8 cases, not GA evidence, not a gate, and not a confidence
estimate.** Output on the working tree (6 of 8 pass per arm):

| Case | Direct | Linked | What it shows |
| --- | --- | --- | --- |
| two facts needed (owner + leave) | miss `leave` | pass | The link helps (3.1). |
| same person, irrelevant property | pass | extra `hobby` | The link harms (3.1). |
| sibling scope supplies the bridge | pass | pass | Scope isolation holds in this case. |
| unreviewed auto-extracted evidence | pass | pass | Trust gate holds in this case. |
| no anchor in the question | pass (empty) | pass (empty) | Abstains when nothing is lexically anchored. |
| current value after keyed correction | pass | pass | Keyed supersession hides the old fact. |
| current fact versus stale conversation | extra `obsolete_turn` | extra `obsolete_turn` | **Open gap** (3.2). The fixture is an unkeyed old episode plus a current fact. No supersession happens in this case. |
| budget with headers and episode | pass (30/40) | pass (30/40) | The cap holds in this case only. |

### 2.4 Published results and what they do not show

From `README.md` and `bench/results/*.json`. All author-run on one 8-core CPU box, one run per arm, no
confidence intervals. **None of the rival comparisons below was re-run on the hardened `main` (#14, #15
postdate them), so they say nothing about current code versus those rivals.**

| Result | Says | Does not say |
| --- | --- | --- |
| LongMemEval_s, 100 test questions | Retrieval is competitive. No-model `recall_all@10` 0.89 vs FTS5 0.87, mem0 hybrid (`infer=False`) 0.93. | Retrieval only, session level. Weights tuned on a disjoint dev split of the same dataset. Abstention questions skipped. Mem0 ran with `infer=False`. |
| LoCoMo, 1,536 QA | No-model 0.641 `recall_any@5` vs FTS5 0.606, mem0 hybrid 0.564. | Retrieval only. Single run; the 3.5-point gap to FTS5 has no interval. |
| 200-fact E2E, 100 questions | Teresis 100% (99/99 clean), mem0 `infer=True` 93/93 clean, zero vs 88 write-time LLM calls. | Clean accuracy drops answer-call 429s (1 vs 7), so arms have different n. One run, one answer model, author fixture. |
| Hermes live, 100 questions (scale mode) | 100/100 with Teresis vs 60/100 stock Hermes. 20 changed-value questions with the old value forbidden; 10 never-told questions. | All 90 answerable questions share a project cue with their fact (the 10 never-told ones have none), so it cannot show what embeddings or links add. The 30-fact version tied 29/30. Stock Hermes overflowed a 3,200-character file, a weak baseline. |
| Built-in bench | Latency: recall p50 14 ms, p95 21 ms at 10k. | Author fixture, lexical defaults tuned on it. Measures `recall`, not full prefetch. |

Measured only narrowly: old values in the final answer (the 20 live and 20 E2E update questions), abstention (10 author-
written questions in each of live and E2E), scope leakage (leak@5 in the built-in bench). Not measured: stale
episodes in a packet, unreviewed, forgotten or expired exposure, scope or trust failures against rivals,
real-token cost, cold start, Graphiti or Hindsight, and any rival comparison on the hardened code.

### 2.5 What the rivals document (to place the design, not to rank)

- Mem0 `add`: `infer=True` (default) extracts structured memories with a model; `infer=False` stores raw
  messages. [docs](https://docs.mem0.ai/core-concepts/memory-operations/add)
- Graphiti: temporal knowledge graph with entity and edge extraction, a bi-temporal model, fact
  invalidation and hybrid retrieval. [overview](https://help.getzep.com/graphiti/getting-started/overview)
- Hindsight: `retain` (an LLM extracts facts and entities and builds graph links), `recall` (semantic,
  keyword, graph and temporal strategies run in parallel, fused and reranked) and `reflect`.
  [methods](https://hindsight.vectorize.io/developer/api/main-methods)

The shared pattern is model-based extraction at write time. Teresis moves the model out of the hot path and
keeps validity intervals and the trust gate. Graphiti's invalidation model is the closest design reference;
Hindsight and Mem0 `infer=True` are the strongest LLM-backed rivals to test against.

## 3. Evidence design

### 3.1 Typed relations versus co-mentions

**Current code.** `memory_entities` records that a memory *mentions* an entity (explicit `[[X]]`, `@x`, host,
path, or a capitalised span seen in at least two memories). A co-mention carries no predicate. `unique_peers`
(WIP) admits a peer only when exactly two active durable rows in the same scope share a traversable entity.

**Where the unique link helps.** Store `Priya owns the billing service.` and `Priya is on leave through
October.` Ask "Is the billing service owner available?" Direct retrieval admits only the owner row, because the
leave row shares no question term (prototype: miss `leave`, 23 tokens). The link follows `Priya` to the single
other row and admits it, labelled `linked from <id>` (56 tokens).

**Where it harms.** Replace the leave row with `Priya collects vintage fountain pens.` Same question, same
link, and the hobby row is admitted (prototype: extra `hobby`). The link knows Priya is shared; it cannot know
*which property of Priya matters*.

**Why uniqueness is only a damage cap.** If a third Priya row appears, `len(rows) != 2` and nothing is
admitted, so the helpful case disappears too. Coverage then depends on how many rows mention a name, not on
relevance. Co-mentions stay default-off, as an experiment arm.

**Proposal: typed relations.** A `relations` row is `(id, scope, subject_entity, predicate, object, evidence_id,
valid_from, valid_to, status, origin)`. The evidence row must be active and in the same scope; a relation is a
view over its evidence, not a copy (4.3). Predicates come from a small closed set, extracted by rules first:
`owns`, `availability`, `uses`, `listens_on`, `prefers`. The query side gets a rule-derived *intent class*. A
peer is admitted only when its predicate class matches:

- `owns(Priya, billing)` is the anchor; the question's `available` cue selects class `availability`.
- `on_leave(Priya)` is class `availability`, so it is admitted and cited with its relation.
- `collects(Priya, fountain pens)` is class `interest`, so it is not.

Rules that cannot assign a class produce no relation, so the system abstains instead of guessing. M6 ships
only if it beats the co-mention arm on the dev split and adds no forbidden injections.

### 3.2 Stale captured episodes

**Gap (prototype case 7).** The fixture holds an unkeyed old turn (`User: The Kestrel worker listens on port
4400.`) and a current keyed fact (6600). Nothing links them, so prefetch injects both and the model sees two
ports. The fixture does not show keyed supersession: that is covered by case 6, where the old keyed row is
hidden.

**Proposal: a render-time overlay, not an erasure.** Episode content is never rewritten. When a keyed fact is
superseded (or `update` changes a value), the overlay looks for active same-scope episode text that asserts the
old value. Evidence is used in this order:

1. **Linked spans.** Where extraction recorded the evidence id and span for the old fact, flag that span.
2. **Conservative single-claim match.** Flag a *whole* episode only if it contains a single claim-bearing
   statement that shares at least two distinctive terms with the old fact, contains the old value and not the
   new one. Anything ambiguous is not flagged.
3. **Mixed-topic episodes stay.** An episode with several topics is never flagged as a whole. Only the stale
   span is omitted at render time (`[stale span omitted]`); unrelated text is still eligible.

Case 7 has no supersession event to trigger this work. For a newly established keyed fact, M3 must also
reconcile earlier episodes where a single span names the same subject and field with a different value
(for example, Kestrel's worker port). A different number and a shared project name alone are not enough.

Flags are metadata (`meta.stale = [{span, superseded_by, at, rule}]`). Consequences, stated plainly:

- Episode *content* is not mutated. Metadata changes **are** persistent writes: they appear in exports and
  syncs and must be logged and reversible with `teresis review`. The "packet building writes nothing" rule
  (3.3) applies to reads, not to the supersession-time flagging.
- A meta-only update should not need an FTS reindex or schema change; M3 verifies this.
- A false flag hides a span from current-intent packets only; the row, history and exports keep it.
- Unkeyed facts are not covered, and episodes still expire by TTL (30 days).

**Ephemeral evidence.** At most two eligible episodes may follow durable facts. They never serve as a bridge
and expire by default. Candidates stay in quarantine and are never injected; raw tool output is not a
separate packet input. Durable facts can already carry `ttl_days`. Inferring a validity date from
"through October" would be a model proposal (4.3), not a deterministic rule.

### 3.3 The disclosure gate and the packet contract (proposal, extends the WIP container)

Two questions are kept apart: *was this row applicable then?* (temporal) and *may we show it now?*
(disclosure). The current store `as_of` answers only a validity-interval question; it does not enforce the
disclosure policy below, so the packet builder applies it on top.

**Disclosure gate. Always applied, for current *and* historical intent, and independent of `as_of`.** An
automatic prompt may never contain a row that is:

- outside a readable scope;
- forgotten (soft-deleted);
- expired **at the current clock**, even if it was live at the requested time;
- unreviewed, a candidate, or flagged as system or injected text (`provenance.injectable` fails).

A row that existed at the requested time is never resurrected by that fact. The gate does not take a requested
time as an input.

**Temporal applicability.**

- *Current intent* (default; ambiguous resolves to current): only versions active now.
- *Historical intent* (rule cues such as "was", "before", "originally", "used to", "as of <date>"): may also
  admit superseded versions or flagged spans that **pass the disclosure gate and were valid at the requested
  time**. Each is rendered with its validity interval or date (`[valid 2026-03-01 to 2026-06-12]`). With an
  explicit date, show the version valid on that date, not today's replacement. A question explicitly
  comparing then and now can request both dates and gets separately labelled evidence for each.

An item is shown iff the gate passes now **and** it is applicable at the requested time.

**Explicit archival tools** (`memory_recall` with `as_of`, `history`, candidate listing for review) are a
different contract with their own permissive semantics. Their design is out of scope here and they are not
used by automatic prefetch.

**Packet items** carry `id`, `kind`, `key`, `scope`, `version/validity`, `origin/trust`, `role`
(`direct | linked | episode | historical`), `via` and a machine reason code. Invariants, each a property test:

1. `len(items) <= limit` and `estimate_tokens(rendered) <= budget`, including headers and citations.
2. Every item passes the disclosure gate, evaluated at the build clock, for any intent and any requested time.
3. Under current intent no superseded version and no flagged span is rendered. Under historical intent every
   such item shows its validity, and the date-matching version ranks first.
4. Rendering is deterministic for a fixed store and clock.
5. Building a packet performs no writes, including no `access_count` updates.
6. Empty is valid. The reason (`no_anchor`, `below_floor`, `budget_zero`) is available to `explain` and never
   injected.

Fixtures must include rows forgotten, expired-now, candidate and system-flagged but valid at the requested
time, and a mixed-topic episode with one stale span.

## 4. Architecture

### 4.1 Data flow

`[P]` marks proposals. Unmarked boxes exist today (the packet stage is WIP).

```
 WRITE (sync, no network)                        READ (sync, bounded, no network by default)
 Hermes hooks: sync_turn / on_memory_write       Hermes prefetch(query)
        |                                               |
   trust gate -> redact -> provenance              [P] intent class (current | historical)
        |                                               |
   episode | fact | candidate --> SQLite (WAL) <-- recall: FTS5 + trigram [+ vectors]
        |            | keyed supersede                  |
        |            +--> [P] stale-span overlay   direct facts -> [peer, default off] -> episodes
        |                                               |  disclosure gate + hard cap (WIP packet)
        |                                         injected text (or empty)
        +--> [P] enqueue ambiguous items
                      |
              [P] ASYNC WORKER (off by default; local generative model, idle, rate-capped)
                      |
              [P] proposals(evidence_ids, model_id, prompt_hash) --> candidate / relation(pending)
                      |
              existing `teresis review` (candidates) extended [P]: approve, reject, invalidate
```

### 4.2 Interfaces

| Interface | State | Notes |
| --- | --- | --- |
| Hermes hooks (`prefetch`, `sync_turn`, `on_memory_write`, `on_pre_compress`) | code | Unchanged. |
| `plugins.teresis.prefetch_k`, `prefetch_budget_tokens`, `prefetch_linked`, `prefetch_min_score` | code / WIP (`prefetch_linked`, full-block budget) | `README.md`, Hermes section. |
| `evidence.build_packet(store, query, scopes, limit, budget, options) -> Packet` | code (M2) | Hermes prefetch, `teresis packet` and `bench/hermes_packet.py` run this one code path; the bench reads the structured items and reason codes instead of parsing citations. The `memory_context` tool (MCP and HTTP) is a different contract and does not use it. |
| `teresis packet "<query>" --scope S --explain` | code (M2) | Dry-run packet with per-row reason codes. Read-only. |
| `plugins.teresis.prefetch_intent: auto\|current` | proposal (M3) | Escape hatch if intent rules misfire. |
| `plugins.teresis.proposals: off\|local\|hosted`, `proposal_url` | proposal (M7) | Default `off`. |
| `teresis review proposals / accept / reject / invalidate / purge --model X` | proposal (M7) | Extends `teresis review`. |

### 4.3 Progressive, optional, async model proposals (proposal)

Generative intelligence is applied only where deterministic rules flag ambiguity (candidates, correction
cues, entities with no predicate), never per turn on everything. Nothing is installed or called by default.

1. **Rule first.** The deterministic extractor runs on write as today.
2. **Enqueue.** Ambiguous items go to a bounded queue (size and per-day caps; overflow drops the oldest item
   and counts it).
3. **Async worker.** Opt-in, runs when idle, calls a *local* endpoint (Ollama or llama.cpp style). Input is
   the best-effort-redacted evidence text and nothing else from the store.
4. **Proposal record.** `(id, scope, kind: fact|relation|supersede|valid_until, payload, evidence_ids[] with
   quoted spans, model_id, prompt_hash, created_at, status: pending|accepted|rejected|invalidated)`. Scope is
   copied from the evidence and cannot widen; a proposal cannot span scopes.
5. **No promotion by the model.** A proposal only creates a `candidate` or `pending` relation, which is never
   injected. Promotion requires **verified human evidence** (the cited evidence turn passes the trust gate as
   human-authored and carries a strong marker, or the same human-authored claim is corroborated across 2
   sessions on 2 days) **or explicit human approval** in review. A marker, repetition or confidence appearing
   in model-generated text or in the proposal payload never promotes anything. Model confidence is displayed,
   never used as a rule.
6. **Review and invalidation.** Derived rows are valid only while every evidence row is active. The packet
   builder joins to evidence at read time, which matters because `forget` is a soft delete and a foreign-key
   cascade fires only on hard delete. Revoking a model or prompt (`purge --model X`) marks its proposals and
   derived rows `invalidated` in one transaction.
7. **Deletion.** `forget` on evidence removes derived rows from packets at once (the join) and from disk at
   purge. Proposal text containing a deleted turn's content is deleted with it.
8. **Failure isolation.** Worker down, model missing or slow: the queue grows to its cap and the read path is
   unaffected. No packet ever waits on the worker.

A local model that shows no supported gain at the declared budget (the section 7 rule, against the
deterministic arm) stays experimental or is removed.

## 5. Alternatives

| Option | Gains | Costs and risks | Decision |
| --- | --- | --- | --- |
| **Deterministic lexical, embedded** (code) | No network or model cost; recall p50 14 ms at 10k (author fixture); deterministic and auditable | Weak on paraphrase and implicit multi-hop; relies on the question sharing a term | **Ship, default** |
| **Embedded retrieval models** (optional embeddings via Ollama or an OpenAI-compatible URL; `fastembed` reranker; code) | Local, one config key; best published retrieval | Reranker p50 738 ms on LoCoMo; embeddings about 180 ms recall without numpy; extra install; the reranker's model files may be downloaded on first use; a hosted `embed_url` sends redacted-best-effort text off-box | **Ship as opt-in** (already is) |
| **Local LLM async proposals** (proposal) | Can find relations and corrections that rules miss, off the hot path | CPU contention; non-determinism; prompt injection through captured text; needs review UX | **Later: experimental, opt-in, M7/M8, gated** |
| **Optional hosted inference** (BYO OpenAI-compatible) | Better extraction quality; no local GPU | Egress of memory text; cost; vendor variability. Needs consent and redaction first | **Later, only if local fails and users ask; never default** |
| **Managed service** (Zep, Mem0 platform, Hindsight cloud) | Fastest to rich graph features | Violates local-first; data leaves the machine; vendor lock; cannot guarantee scope or trust semantics | **No. Baselines only, with consenting synthetic or public data** |

## 6. Storage, privacy and rollout

### 6.1 Boundaries

- **Scopes are namespaces, not access control.** Anyone who can open the DB file, call the MCP server or
  reach the HTTP API (`127.0.0.1`, optional bearer token) can read every scope. Scopes prevent *accidental
  cross-talk* between cooperating agents, not a hostile process. For isolation use separate DB files
  (`db_path`), the only hard boundary offered here. The README says so.
- **Derived data never widens scope.** Overlay flags, relations and proposals take the scope of their
  evidence; a cross-scope link is invalid by construction.
- **Default network posture:** none. Egress today happens only through an explicitly configured `embed_url`,
  and through `proposal_url` if M7 ships. Optional reranker model files may be downloaded on first use.
- **Redaction is best-effort pattern matching on content.** It is not a guarantee about metadata (keys, tags,
  source, scope names, entity names) or about everything sent to an embedding or proposal endpoint. Do not
  point those at an endpoint you do not trust with your memory text.
- **No telemetry or audit claim.** No egress counter or audit log exists. Any such claim waits until it is
  implemented and tested.
- **Benchmarks and design work use synthetic or public data only.** No real agent memory is read and no paid
  service is called unless its owner consented to that specific run.

### 6.2 Upgrade, backup and rollback

- **No promise that an older binary can open a newer DB.** `MemoryStore` stamps its schema version on every
  open and migrations are only `CREATE IF NOT EXISTS`, so an older writer would overwrite a newer stamp and a
  future column change has no migration path. Before any schema change, new code must refuse a schema newer
  than it knows, apply numbered migrations, and take an **online SQLite backup into a separate file** before
  the first migration of a database.
- **Rollback = restore that backup into a separate file and run the matching pinned binary.** Never reopen an
  upgraded live DB with an older writer. Writes made after the backup are not recovered by this path.
- **JSONL is a logical export.** It carries what `export` documents (ids, content, keys, scopes, history).
  It does not carry manual graph links or vectors. Round-trip tests cover only what it includes. The online
  backup is the only complete copy of derived and index state.
- **Per-feature rollback is configuration:** `prefetch_linked=false`, `prefetch_intent=current`,
  `proposals=off`.
- **Release channel:** tag `0.2.0rc1` on GitHub (distribution is GitHub-only) for the author's profile and
  volunteers, then GA. A local tool has no percentage rollout, so the gate is evidence, not time.

## 7. Release protocol

Two things are kept apart. **Hard gates** decide whether we ship. **Claims** decide what we may say. Failing
a superiority test limits the claims. It never blocks shipping and is never read as a tie.

### 7.1 Hard gates (all required to ship GA)

- **Exposure:** zero scope, trust, forgotten, expired or unreviewed exposures across the property tests and
  the adversarial release challenge (sibling, unreviewed, system-text, injection, forgotten-but-valid-then).
- **Budget:** zero over-budget packets by the documented estimator, and a real-token overshoot rate reported
  next to it. If it is nonzero the estimator is made conservative; the claim is not weakened.
- **Latency:** p95 <= 50 ms warm lexical prefetch at 10,000 memories on a named reference CPU (record
  `lscpu`), with no network and no generative model in default operation.
- **Hygiene (7.3).**
- Unit, replay and diagnostic cases (including `hermes_packet`) are regression checks. They are not samples
  and never produce a confidence estimate.

### 7.2 Superiority claims (optional, per provider)

1. **Freeze** dev, held-out and challenge sets by user and conversation. No turn is shared across them (exact
   hash plus a near-duplicate threshold). Repeated questions about the same history are kept together. Tune
   only on dev. The held-out set stays sealed through tuning and is run once per release candidate, logged.
2. **Same inputs for every provider:** the same raw turns, the same context budget (the same estimator, real
   tokens also recorded) and the same answer model at temperature 0.
3. **Report separately** retrieval-only and end-to-end, and cold (fresh process) and warm.
4. **Count failures.** A timeout, 429 or crash is a failed item for that provider and stays in n. An
   unavailable provider is listed as `not run: <reason>`, never as zero or omitted.
5. **Metrics:** all-required-evidence present, forbidden or stale injection, abstention (correct and false),
   answer correctness, estimated and real prompt tokens, p50/p95 read and write latency, and cost including
   every write-time model call.
6. **Baselines:** stock Hermes (built-in memory); SQLite FTS5 with the same scope filter; the current
   release (`v0.1.0`); dense-only with the same embedder; Mem0 with inference on and off; and, optionally and
   only with consenting or synthetic data, a cloud service, Graphiti or Hindsight. Where a rival cannot honor
   scopes, its scope violations are counted.
7. **Decision rule, per named provider X.** Predeclare one primary endpoint (answer correctness) and one
   budget. Compute the paired improvement over X by cluster bootstrap (resample whole histories with
   replacement, the same clusters for both systems, fixed seed, 10,000 draws).
   - If the predeclared paired 95% interval of the improvement has lower bound > 0: **supported gain vs X**.
   - Otherwise report the observed difference and interval as **inconclusive**; if the upper bound is < 0,
     report a **loss**.
   - No tie or equivalence claim without a separately preregistered equivalence margin and test.
   - Claims are per provider, per configuration, per dataset. Nothing is said about untested providers, and
     there is no global "beats all" and no merged leaderboard.

### 7.3 Hygiene gates

- **Install:** the wheel installs in a clean venv and `teresis hermes install --activate --dry-run` succeeds.
- **Upgrade:** a `v0.1.0`-created DB is backed up, migrated, and then returns the same frozen packets as a DB
  built from the same inputs by the *same target binary*. We do not require reproducing the old binary's
  retrieval, which may change on purpose. A synthetic DB with a newer schema stamp is refused with a clear
  message.
- **Backup and restore:** online backup restored into a separate file reproduces the same frozen packets and
  history. JSONL `export`/`import` into an empty DB is tested only for the fields it carries, with fixtures
  that use no manual links or vectors.
- **Package versions:** `pyproject.toml`, `__version__`, `plugin.yaml` and the git tag agree, enforced by a
  test.
- **Supported Hermes versions:** declared in the README and plugin manifest, and each declared version is
  tested. This is separate from package-version agreement. Today only 0.23.3 is tested.
- **Benchmark integrity:** result files record commit, config, seed, CPU and answer-model id, and the README
  quotes only runs made on the release candidate.

## 8. Milestones

| ID | Milestone | Depends on | Exit |
| --- | --- | --- | --- |
| M0 | Land the packet slice (cap, no reinforcement, order, `prefetch_linked` off) | none | Hard contracts green (budget, no-write reads, trust, scope). `hermes_packet` misses recorded (today: cases 1, 2, 7), not required to be zero, since the linked arm is a default-off experiment |
| **M1** | **Freeze and measure.** Dev/held-out/challenge sets, one harness for all baselines, cluster bootstrap, first run on `v0.1.0` and `main` | none (parallel with M0) | Baseline table with caveats and a reproducible command; unavailable providers listed |
| M2 | One packet builder (`evidence.build_packet`) with structured items, reason codes, `teresis packet --explain`, property tests for the 3.3 invariants | M0 | Zero over-budget and zero gate violations in fuzz; bench consumes the structured packet |
| M3 | Stale-span overlay, disclosure gate, current/historical intent | M2; M1 for evaluation | Case 7 passes; mixed-topic and historical-intent fixtures pass; zero gate exposures on the challenge set |
| M4 | Hygiene: schema guard, numbered migrations, backup/restore and upgrade tests, version and Hermes-version checks | none | 7.3 passes in CI |
| M5 | Decide the `prefetch_linked` default from paired data (co-mention versus direct) | M1, M3 | Default on only if the predeclared paired lower bound over the direct arm is > 0 with zero new forbidden injections; otherwise it stays off |
| **GA** | Release candidate (M0 to M5), full protocol | all above | 7.1 and 7.3 pass; published claims limited to those supported under 7.2 |
| M6 | Typed relations (rules only) | M5 result | Paired lower bound > 0 over the co-mention arm on dev, then challenge passes |
| M7 | Proposal framework with a fake deterministic proposer, tables, review, invalidation, deletion | M4, M6 | Deleting evidence removes derived rows from packets; model-written markers never promote; no model required |
| M8 | Local model adapter, experimental | M7, M1 | Supported gain over the deterministic arm at the same budget, else removed |
| M9 | Hosted adapter | M8 and user demand | Consent and redaction in place, and egress accounting implemented and tested before any such claim; never default |

Order: M1 and M0 in parallel, then M2, M3, M4, M5, GA. M6 to M9 are post-GA.

## 9. Strongest objection and response

**Objection.** A deterministic packet that prefers silence may lose to LLM-backed memory on what Hermes users
actually ask: paraphrases, implicit preferences and multi-hop questions with no shared term. The unique-link
prototype shows co-mention cannot decide relevance. The 100/100 live run's answerable questions all share a
project cue with their facts, so it says little about those cases. "Beat both" may be unreachable without a
model in the read path.

**Response.** The objection may be right, and the plan finds out cheaply. M1 measures where required evidence
is missing: if the misses cluster in anchor-free paraphrase and multi-hop, that is the only place selective
intelligence is justified, and M8 competes on those items only. If a local proposal arm cannot show a
supported gain at the same budget, we report the observed difference with its interval as inconclusive or a
loss. That is a statement of what we do not know, not "tie with Mem0 at zero write-time model cost". The
cost and determinism properties stand on their own and are reported as such. A generative model in the read
path is rejected because it breaks the latency, offline and determinism targets that are the product.

## 10. Deliberately unresolved

- How intent cues are tuned, and their error rate on real prompts (M1 data decides).
- Whether extraction can reliably record evidence spans for the overlay's linked-span path.
- Unkeyed contradictions ("prefers vim" then "prefers emacs") beyond the keyed case.
- Archival tool semantics for forgotten or expired rows.
- Which hosted providers, if any, to test, and who consents to what data.
