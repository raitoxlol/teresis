# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who run AI agents — Hermes Agent, Claude Code, Codex, and other MCP clients — and want those agents
to remember facts, preferences and decisions across sessions without sending data to a cloud service.

## Product Purpose

Teresis (τήρησις, "faithful keeping") is local long-term memory for AI agents. It stores everything in one
SQLite file and has no dependencies. Success: an agent recalls the right, current fact on the next turn, offline,
in milliseconds, and never contradicts itself with a stale value.

## Positioning

- Deterministic writes: no model call per turn. Duplicates reinforce, keyed facts supersede and keep history,
  so the newest value wins and `history` / `as_of` show the timeline.
- Scopes are paths (`global`, `user`, `project/atlas`, …): recall sees a scope and its parents, never siblings.
- Fully local and offline; optional embeddings from Ollama or any OpenAI-compatible server.

## Operating Context

Installed next to an agent runtime: a native Hermes memory provider, an MCP stdio server, a local HTTP API,
a CLI and a Python API, all sharing one store. Several agents can share it at once (WAL mode).

## Capabilities and Constraints

- Distribution: **Apache 2.0 open source** at `https://github.com/raitoxlol/teresis` and PyPI (`pip install teresis`).
- Primary conversion while private: **waitlist sign-up**. Provider not chosen yet.
- Install commands may appear only as a preview for people who already have access.

## Brand Commitments

- Name: Teresis. Mark: L3 lotus fan on a 30-60-90 grid, corner radius 4 (`brand/logo/`).
- Wordmark: undecided. The user wants a custom wordmark drawn on the mark's grid, done later; a stand-in is
  used until then.
- Brand colour in README: Manuscript Ochre `#A67A2A` (dark-mode `#D9AF5B`).

## Evidence on Hand

All approved for publication, from `README.md` and `bench/results/`:
- Live Hermes test: Hermes + Teresis 100/100 vs stock Hermes memory 60/100, by question kind
  (`site/src/content.ts` LIVE_BY_KIND).
- LoCoMo: Teresis + all-minilm 0.654, Teresis no model 0.637, holographic 0.563, mem0 OSS 0.449.
- LongMemEval: Teresis + all-minilm 0.936, mem0 OSS 0.903, Teresis no model 0.882, holographic 0.859.

No testimonials, customers, pricing, user counts or press exist; never invent them.

## Product Principles

1. Keep facts straight: the current value, with its history, beats a pile of notes.
2. Local by default: nothing leaves the machine unless the user adds an embedder.
3. Deterministic and inspectable over clever and opaque.
4. Claims stay tied to reproducible numbers in the repo.
