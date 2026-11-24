# Draft upstream issue (not filed): pass an explicit `turn_origin` to memory providers

Target: Hermes Agent, `MemoryProvider.sync_turn` / `on_pre_compress`.

## Problem

`sync_turn(user_content, assistant_content, *, session_id, messages, turn_author)` receives text in the
`user` role that no person typed: kanban dispatcher task bodies, gateway notices, cron and webhook wake
messages, compaction summaries and quoted memory-context blocks. A provider that learns from "what the
user said" cannot tell these apart. `turn_author` helps only when the dispatcher sets it, and it is
absent for ordinary chat turns, so a provider must guess from the platform name.

`on_pre_compress(messages)` is worse. The list mixes system prompts, assistant and tool messages and
model-written compaction summaries, none of it labelled.

A memory provider in the wild extracted system-prompt rules and compaction sentences as durable
"user preferences" because of this, and replayed them into later prompts as facts.

## Proposal

Pass an explicit origin for the turn, additive and optional like `turn_author`:

```python
def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None,
              turn_author=None, turn_origin=None): ...
```

`turn_origin` is one of:

| value | meaning |
| --- | --- |
| `"human"` | a person typed it |
| `"system"` | gateway or runtime notice |
| `"kanban"` | kanban dispatcher task body |
| `"cron"` | scheduled job or webhook wake message |
| `"injected"` | memory context, compaction summary or other runtime-injected text |

Also tag each entry in the `messages` list given to `on_pre_compress` with the same field (or a
`compaction_summary: true` flag), so providers can skip summaries without parsing prose.

The manager keeps sending it only to providers whose signature accepts it, as it does for `turn_author`.

## Compatibility

Providers that ignore the argument behave as today. Teresis currently derives the same decision from
`turn_author` and `platform` and will prefer `turn_origin` when present.
