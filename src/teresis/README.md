# Teresis for Hermes

Teresis adds a local SQLite memory store to one Hermes profile, alongside Hermes's
built-in memory. It can share a database with other local agents using Teresis MCP.
No account or API key is required for local lexical search.

For a local Teresis CLI install, choose an existing profile and database:

```sh
teresis hermes install --activate --profile work --db /absolute/path/memory.db
hermes --profile work memory status
```

The command will not switch away from an existing external provider. For an install
managed by Hermes, use `hermes --profile work memory setup` and select Teresis.
Check the database path and start a new session. Use a separate database for profiles
that should not share memory. Scopes organize retrieval within a file; they are not
authorization boundaries.

Teresis automatically saves dialogue as searchable episodes with a 30-day default
TTL, and can extract durable preferences and decisions. You can disable turn capture
and extraction in that profile's provider settings. Existing Hermes memory files
are not imported by setup. Credential-pattern redaction is best effort, not a
guarantee that all sensitive text will be removed.

By default the provider does not make network or model calls. Explicitly configuring
an embeddings endpoint sends input and search text to that endpoint; use a trusted
local endpoint if the text must stay on-device. Optional reranking can download a
model and runs inference locally. No credentials are required by the plugin manifest.

See the [Teresis repository](https://github.com/raitoxlol/teresis) for store behavior,
settings and the shared MCP setup.
