# Page copy

## Head

Title: Teresis: local long-term memory for AI agents

Description: One SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Facts keep their history, and writes make zero LLM calls.

## Navigation

Try it · Method · Works with · Benchmarks · Questions · GitHub · Install Teresis

## Hero

Local long-term memory for AI agents

Teresis keeps facts, preferences and decisions in one SQLite file shared by Hermes, Claude Code, Codex and other MCP clients. Writes make zero LLM calls.

Install Teresis · See the benchmarks

Live Hermes test: 100/100 with Teresis, 60/100 with stock memory.

## Guided terminal

Guided terminal

Run next command · Start over

## Method

How Teresis keeps facts straight

One SQLite file · Changed facts keep history · Stemmed search and trigrams · Zero model calls on writes

Recall reads a scope and its parents, never a sibling. User is a sibling of projects.

File · Fact · Scope · Key · History · Recall · Write

## Compatibility

Works with agents and APIs

Hermes Agent uses a native memory provider. Claude Code, Codex and Cursor connect through MCP.

HTTP · Python

## Statement

Your agents forget. Teresis keeps.

τήρησις is Greek for faithful keeping.

Secrets are redacted on write. Nothing leaves the machine unless you add an embedder.

## Benchmarks

Benchmark results

Live in Hermes · 200-fact run · LongMemEval · LoCoMo

Live Hermes test: 100/100 with Teresis, 60/100 with stock memory.

A real Hermes agent was told 200 facts across earlier sessions, then asked 100 questions in fresh sessions with nothing restated. Graded by string match, no AI judge.

One run per arm, seed 42. A 30-fact version of the same run was a tie, 29 of 30 each: the gap appears once memory outgrows the built-in 3,200-character file.

Lookup in the Teresis store took a median of 6.6 ms (p95 8.5 ms).

The same 200 facts and 20 updates go into each system, then 100 questions with the same answer model at temperature 0. Graded by exact string match.

Read the result files on GitHub

## Install

Install Teresis

One SQLite file for Hermes, Claude Code, Codex, Cursor, MCP, HTTP and Python.

Copy the commands · Copied

## Questions

Questions about Teresis

Does Teresis send anything off my machine?

No. Teresis stores everything in one local SQLite file. Embeddings are optional; if you turn them on, they come from an Ollama or OpenAI-compatible server you choose.

Does Teresis need a GPU or a model?

No. Without embeddings it runs on keyword and fuzzy search alone, in milliseconds on a laptop CPU. Embeddings add paraphrase matching.

Which agents does Teresis work with?

A native memory provider for Hermes Agent, an MCP server for Claude Code, Codex, Cursor and every other MCP client, plus HTTP and Python APIs. All share one store.

Can several agents share one memory?

Yes. Scopes keep projects apart, and SQLite WAL lets several processes write at once. Subagents and crons can run read-only.

How is Teresis licensed?

Apache 2.0. Install with Homebrew, pip from GitHub, or download teresis.pyz from GitHub Releases.

## Close and footer

Run the install command

Copy the Homebrew install command

Read the source on GitHub

Subscribe to release notes

Release notes only.

Teresis · Apache 2.0 · Product names and logos are trademarks of their owners.
