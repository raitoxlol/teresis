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

## Data, network and processes

- Teresis reads the Hermes profile settings via Hermes and opens the selected
  SQLite file (including WAL sidecars). It can mirror native memory-tool writes,
  capture dialogue as searchable episodes with a 30-day default TTL, and extract
  durable preferences and decisions. Turn capture and extraction are configurable.
  Setup never imports existing Hermes memory files. The separately invoked
  `teresis hermes import` CLI command reads the profile's `MEMORY.md` and `USER.md`.
  Credential-pattern redaction is best effort, not a privacy guarantee.
- Lexical mode, the default, makes no provider network or model calls and requires
  no credentials. The provider does not emit telemetry. Explicit Ollama or
  OpenAI-compatible embeddings send text and queries to the selected profile's
  configured endpoint. Use a trusted endpoint; local endpoints keep this traffic
  on-device. Hermes reads optional `TERESIS_EMBED_KEY` through its active profile
  secret API for OpenAI-compatible embeddings. `embed_auth: none` sends no bearer.
  A bearer requires HTTPS or loopback HTTP; redirects are refused. The key is not
  saved by Teresis. Optional fastembed reranking may download model artifacts and
  runs inference locally. These settings are per-profile; standalone environment
  switches do not enable remote embedding or reranking inside Hermes.
- Activating the native plugin starts no background service or self-updater.
  Separate standalone commands can invoke the Hermes CLI to configure a profile,
  run SSH to transfer an encrypted sync bundle, or start a foreground HTTP API
  or inspector. Both listeners default to loopback; the optional UI token protects
  writes, not reads. The inspector may open the browser. Those commands do not run
  during Hermes activation.

See the [Teresis repository](https://github.com/raitoxlol/teresis) for store behavior,
settings and the shared MCP setup.
