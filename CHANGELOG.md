# Changelog

## v0.1.1 (public preview)

A public preview, not GA. v0.1.0 had no protection against saving system text as memory. This release does.

### Added
- **Trust gate and provenance for auto-capture.** Teresis extracts durable memories only from turns it can show were typed by a person. Bot, system, cron, webhook and kanban turns are kept as episodes but never promoted.
- **Candidate quarantine.** Doubtful extractions are held as candidates instead of becoming memories.
- `teresis review` to inspect and promote or reject candidates, `teresis doctor` to check an install, `teresis scrub` to remove memories that should not have been saved.
- Hermes import (`teresis hermes import`) and one-command Hermes wiring.
- Local inspector (`teresis ui`), entity graph and encrypted sync (`teresis sync`).

- A benchmark for relative-date notes in Hermes (`bench/relative_dates.md`). It measures the behaviour. It does not change the product.

### Fixed
- Gateway notices that arrive as user turns (for example `✔ [default] Kanban t_… done`) are no longer extracted.
- Hermes setup and import stay on the selected profile's database. The DB, embedding settings and credentials are profile-scoped.
- Embedding batches that come back incomplete or are rejected are recovered instead of dropping memories. Automatic Hermes memories are saved before embedding.

### Known limits
- The trust gate relies on the `turn_author` and `platform` Hermes already sends, plus phrase-shape checks on the text. It is a defence by shape until Hermes sends an explicit `turn_origin`. A proposal is in `docs/upstream-issue-turn-origin.md` and has not been filed.
- A clean Hermes-managed install (issue #8) is not yet proven end to end.
- The Hermes catalog submission (NousResearch/hermes-agent #159692) has not been accepted. Install from Homebrew, the wheel, `teresis.pyz` or GitHub.
- The slow-embedding shutdown test from the GA checklist (#10) is not proven.

This release was written and tested with AI assistance.
