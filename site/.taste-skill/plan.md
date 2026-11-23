Kind: software (developer tool). page type software, site-kind software. Sold: local long-term memory for AI agents. Buyer: developers running Hermes, Claude Code, Codex and other MCP clients. Main action: "Install Teresis" -> #install.

Deal: hero `collage`; palette = the client's own colours through `start.mjs brand` (bg #123a2a, surface #0c2b1f, ink #f1e9d6, muted #b8cbb4, accent #d9af5b: the lotus-leaf green and manuscript ochre of the existing mark and README, kept because the logo is drawn in them); type `instrument` (Instrument Sans + DM Mono, first dealt); radius `sharp` (developer tool); nav dealt `nav-cards` -> dealt again to `nav-centre` (no photographs for picture cards); footer `footer-columns`; close `close-word`; rhythm `dark-band` (the live Hermes test on `.ground-inverse`); buttons `solid`; mark: the client's own lotus SVG (dealt `wordmark` replaced by the logo). No shader effect: the dealt hero takes the lit ground in its frame, drawn as the brand's 30-60-90 lattice (page CSS inside the visual). Moments (dealt, seed 7f4d24f7): `liquid-type` on the statement section, `counter-rolls` on the live-test figures. The enchant glint stays as a slow drifting sheen on the ochre statement line and the primary button, recoloured from violet to pale gold (the skill bans violet and lavender as an effect colour).

Voice: technical-dry. Exact, not cold. The product is the subject of feature lines; "you" only in the FAQ. Sentences 8 to 16 words. No humour. House words: file, fact, scope, key, history, recall, write. Never: virtue words, a strip of claims, invented numbers.

Sections (id · idea · picture, kind · screens · moment)
1. hero · what it is, for whom, one hard fact · terminal window on the lattice ground + one result card, object · 1
2. #memory app-frame · every fact with scope, key and history · memory list beside a terminal session, object · 1
3. #how bento · the five rules of a write and a recall · hub diagram + four UI fragments, diagram/fragments · 1 (2 at 768/390 if needed)
4. #keeps statement · the one brand line · type, liquid-type moment · 1
5. #benchmarks dark-band · live Hermes test 100 vs 60 · counter figures + by-kind table, type/table · 1 · counter-rolls
6. #public · LongMemEval and LoCoMo · two bar charts · 1 at 1440, 2 at 768 and 390
7. #install tabs-tour · four interfaces, one file · code frame · 1
8. #questions faq · five questions, open in full · none (the one allowed picture-less FAQ) · 1
9. footer.closing · close-word + footer-columns + release-notes form · the name set wide with the lotus · 1

============ COPY (final; numbers and snippets come from site/src/content.ts, keep them exact) ============

HEAD
title: Teresis: local long-term memory for AI agents
description: One SQLite file that Hermes, Claude Code, Codex and other MCP clients share. Facts supersede with history, and writes make zero LLM calls.
og:title = title; og:description = description.

NAV (nav-centre): Memory -> #memory · Method -> #how · Benchmarks -> #benchmarks · Questions -> #questions · GitHub -> https://github.com/raitoxlol/teresis (plain word, new tab) · button: Install Teresis -> #install

HERO
h1: Local long-term memory for AI agents
lead: Teresis keeps facts, preferences and decisions in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.
buttons: [primary] Install Teresis -> #install · [secondary] See the benchmarks -> #benchmarks
proof line (muted, one line): Live Hermes test: 100/100 with Teresis, 60/100 with stock memory.   (HERO.proof values)
window (terminal, real CLI output, verbatim):
  $ teresis remember "Editor is VS Code" -s user --key user.editor
  created 36a9d8ab412246e3
  $ teresis remember "Editor is Neovim" -s user --key user.editor
  superseded 0c4fed00cb4b4db2 (replaced 36a9d8ab412246e3)
  $ teresis remember "Editor is Neovim" -s user --key user.editor
  duplicate 0c4fed00cb4b4db2
  $ teresis recall "which editor" -s user
  0c4fed00cb4b4db2  [fact · user · key=user.editor · 1.014]
      Editor is Neovim
result card (the one small card, its three steps arrive in the loop): title "user.editor" · rows: "Editor is VS Code — superseded" / "Editor is Neovim — current" / "Repeated write — duplicate, no new row"

#memory (app-frame)
h2: Facts with their scope and history
paragraph: A keyed fact replaces the old value and keeps the previous one. A repeated fact reinforces the same row. Recall reads a scope and its parents. [link] Read the source on GitHub -> https://github.com/raitoxlol/teresis
list pane (window; who = scope, sub = fact · key, chip = state). Sidebar labels: All, user, project, global. Rows:
  user · Editor is Neovim · user.editor · current
  user · Editor is VS Code · user.editor · superseded
  user · User prefers terse answers · preference · current
  project/atlas · Atlas uses PostgreSQL 16 · atlas.database · current
  project/atlas · Deploys go out on Tuesdays · current
  project/atlas/agent-x · Migration 0042 is applied · current
  project/helios · Helios runs on MySQL 8 · helios.database · current
  project/helios · Helios deploys from the main branch · current
  global · Commit messages use the imperative mood · current
  user · Timezone is Europe/Berlin · user.timezone · current
open pane (terminal, real CLI output, verbatim; the pane cuts it under its fade):
  $ teresis history -s user --key user.editor
  36a9d8ab412246e3  [fact · user · key=user.editor · SUPERSEDED]
      Editor is VS Code
  0c4fed00cb4b4db2  [fact · user · key=user.editor]
      Editor is Neovim
  $ teresis recall "postgress" -s project/atlas --explain
  e49ec32acb4f4da0  [fact · project/atlas · key=atlas.database · 1.000]
      Atlas uses PostgreSQL 16
      why: {'channels': {'trigram': 1.0}, 'relevance': 1.0, 'recency': 1.0}
  $ teresis recall "which editor" -s user
  0c4fed00cb4b4db2  [fact · user · key=user.editor · 1.014]
      Editor is Neovim
  $ teresis stats
  {
    "path": "~/.local/share/teresis/memory.db",
    "total": 6,
    "active": 5,
    "superseded": 1,
    "deleted": 0,
    "vectors": 0,
    "embedder": null,
    "scopes": {
      "project/atlas": 2,
      "user": 2,
      "project/helios": 1
    }
  }
  (the stats block matches the 6 CLI writes above, not the 10 list rows: if both are on screen show only the first three commands in the open pane and drop stats, or keep stats below the fade)
aria-label of the frame: Teresis memory list beside a terminal session showing history and recall

#how (bento)
h2: How Teresis keeps facts straight
wide card: title "Shares one file between agents" · body "Hermes, Claude Code, Codex and Cursor read and write ~/.local/share/teresis/memory.db. SQLite WAL lets several processes write at once." · visual: hub diagram, the agents on the spokes (Hermes Agent, Claude Code, Codex, Cursor), hub label "memory.db". Real colour icons only for marks icons.mjs really has; a tool without one is a text label, never a drawn look-alike.
small 1: "Replaces a changed fact" · "The newest value wins. The old one stays in history." · visual: Editor is VS Code (struck, superseded) / Editor is Neovim (current · key user.editor)
small 2: "Reads parents, never siblings" · "Scopes are paths. Recall reads a scope and its parents." · visual: global ✓ / project/atlas ✓ / project/atlas/agent-x · recalling / project/helios · never read
small 3: "Finds stems and typos" · "BM25 on a Porter-stemmed index, trigrams for typos, optional vectors for paraphrases." · visual: recall("postgress") -> trigram · Atlas uses PostgreSQL 16
small 4: "Writes without a model" · "Zero LLM calls on write, so each write is exact and repeatable." · visual rows: recall p50 · no model (LoCoMo) 17 ms / network calls by default 0 / processes writing at once (test suite) 4     (17 ms = LOCOMO "Teresis, no model" note)

#keeps (statement, liquid-type on the headline)
h2 (set very large, two lines): Your agents forget. / Teresis keeps.     (second line ochre with the glint; this is the page's one brand line)
line under it: τήρησις is Greek for faithful keeping. Secrets are redacted on write, and nothing leaves the machine unless you add an embedder.

#benchmarks (dark-band, .ground-inverse)
h2: 100 of 100 on a live Hermes test
lead: LIVE_METHOD verbatim ("A real Hermes agent was told 200 facts across earlier sessions, then asked 100 questions in fresh sessions with nothing restated. Graded by string match, no AI judge.")
counter-rolls figures (two): 100/100 · Hermes + Teresis    |    60/100 · Stock Hermes (built-in memory)       (LIVE_TOTAL)
table "By kind of question" (LIVE_BY_KIND verbatim): columns Kind · Asked · Teresis · Stock Hermes; 5 rows.

#public
h2: LongMemEval and LoCoMo results
two charts, data LONGMEMEVAL and LOCOMO verbatim (label, bar, value, query time; Teresis rows in the accent, others muted):
  caption 1: LongMemEval · ranking quality (NDCG@10) · median query time
  caption 2: LoCoMo · evidence in the top 5 (recall@5) · median query time
fine print (13px+, verbatim from the current page): Retrieval only, no LLM calls. Vector and hybrid systems share local Ollama all-minilm except total-agent-memory (built-in FastEmbed MiniLM, cross-encoder off). The optional Teresis reranker row adds a local MiniLM cross-encoder over the top 15 hits; all other rows are first-stage retrieval. mem0 OSS ran v3 hybrid (BM25 + spaCy + vectors, infer=False). Higher is better.

#install (tabs-tour)
h2: Four interfaces, one file
grey line: A Hermes memory provider, an MCP server, a local HTTP API and a Python API share one SQLite file.
tabs (label -> SNIPPETS key): Install for Hermes -> Hermes · Add to MCP -> MCP · Call over HTTP -> HTTP · Import in Python -> Python. Frame: code panel with the snippet verbatim and a "Copy" control (aria-label "Copy the commands").
note under the frame: Apache 2.0. No required dependencies.

#questions (faq, open in full): h2 "Questions"; the five FAQ entries from content.ts verbatim.

footer.closing
close-word: h2 "The file stays on your machine" · line "Apache 2.0, installed with pip from GitHub." · button Install Teresis -> #install · then the name "Teresis" set across the wrap with the lotus mark.
footer-columns: Product: Memory #memory, Method #how, Benchmarks #benchmarks, Questions #questions · Source: GitHub https://github.com/raitoxlol/teresis, Licence https://github.com/raitoxlol/teresis/blob/main/LICENSE, Benchmark results https://github.com/raitoxlol/teresis/tree/main/bench/results
release notes form (the newsletter, once): label "Email" · button "Subscribe to release notes" · line under: "Release notes only." · sent line: "You are subscribed to release notes." · posts to the existing /api/waitlist endpoint.
legal row: Teresis · 2026 · Apache 2.0 · τήρησις, faithful keeping. If real third-party icons are shown add: "Product names and logos are trademarks of their owners".

============ Changes made in the check rounds ============
- #install h2 is "Four interfaces to one Teresis file"; first tab is "Add to Hermes"; four FAQ questions name Teresis (the checker's copy-headings rule). Tab texts restate README facts.
- The glint: the statement line drifts on a 4 s cycle with the kit's pause button (data-m-loop); the primary button sweeps twice on load and again on hover or focus (the 5 s loop-pause rule).
- The hub diagram's two scroll-reveal findings are waived in waivers.json (the kit's own diagram.js).
- The app-frame's open pane shows a second real CLI session (history, recall --explain) so no view repeats the hero's.
