"""Local memory inspector: `teresis ui` (stdlib only, binds to 127.0.0.1).

Read-mostly single-page app over the same SQLite file every agent uses: browse scopes,
search with the real recall engine, open a memory to see its versions and entities, and
pin / edit / forget without touching sqlite3 by hand.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .store import MemoryStore

_INDEX = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>teresis · memory inspector</title>
<style>
  :root {
    --ochre: #A67A2A; --brass: #D9AF5B; --ink-ochre: #7C591B;
    --parchment: #FAF7F0; --vellum: #F2E8D2; --iron: #131210;
    --line: #E5DEC9; --muted: #6F6A5F;
    --font: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --parchment: #131210; --vellum: #1D1A15; --iron: #F2EFE8;
      --line: #2E2A22; --muted: #A39C8E; --ochre: #D9AF5B; --ink-ochre: #D9AF5B;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--parchment); color: var(--iron);
    font-family: var(--font); font-size: 14px; line-height: 1.45;
  }
  header {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    padding: 14px 18px; border-bottom: 1px solid var(--line);
    position: sticky; top: 0; background: var(--parchment); z-index: 5;
  }
  .mark {
    width: 22px; height: 22px; border-radius: 6px; background: var(--ochre);
    display: grid; place-items: center; color: #131210; font-weight: 800; font-size: 12px;
  }
  .brand { font-weight: 700; letter-spacing: -0.01em; }
  .brand small { font-weight: 500; color: var(--muted); margin-left: 8px; font-family: var(--mono); font-size: 11px; }
  .spacer { flex: 1; }
  input, select, button, textarea {
    font: inherit; color: inherit; background: var(--vellum);
    border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px;
  }
  input[type=search] { min-width: 240px; }
  button { cursor: pointer; }
  button:hover { border-color: var(--ochre); }
  button.primary { background: var(--ochre); border-color: var(--ochre); color: #131210; font-weight: 650; }
  main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 420px); gap: 0; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .list { padding: 12px 18px 40px; min-height: 60vh; }
  .detail { border-left: 1px solid var(--line); padding: 16px 18px 40px; min-height: 60vh; }
  @media (max-width: 900px) { .detail { border-left: 0; border-top: 1px solid var(--line); } }
  .stats { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px; font-family: var(--mono); }
  .stats b { color: var(--iron); font-weight: 700; }
  .row {
    display: grid; grid-template-columns: 1fr auto; gap: 10px;
    padding: 10px 12px; border: 1px solid transparent; border-bottom-color: var(--line);
    border-radius: 8px; cursor: pointer;
  }
  .row:hover { background: var(--vellum); }
  .row.sel { background: var(--vellum); border-color: var(--ochre); }
  .row .content { font-size: 13.5px; }
  .row .meta { font-family: var(--mono); font-size: 10.5px; color: var(--muted); margin-top: 3px; }
  .pill {
    display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10px;
    font-weight: 650; letter-spacing: .04em; text-transform: uppercase;
    background: var(--vellum); border: 1px solid var(--line); color: var(--muted);
  }
  .pill.pinned { border-color: var(--ochre); color: var(--ink-ochre); }
  .pill.superseded { text-decoration: line-through; opacity: .7; }
  .score { font-family: var(--mono); font-size: 11px; color: var(--ink-ochre); }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin: 22px 0 8px; }
  .empty { color: var(--muted); padding: 26px 4px; }
  .kv { display: grid; grid-template-columns: 96px 1fr; gap: 4px 10px; font-size: 12.5px; }
  .kv dt { color: var(--muted); }
  .kv dd { margin: 0; font-family: var(--mono); font-size: 11.5px; word-break: break-word; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { font-family: var(--mono); font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: var(--vellum); cursor: pointer; }
  .chip.explicit { border-color: var(--ochre); color: var(--ink-ochre); }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
  .history { display: flex; flex-direction: column; gap: 8px; }
  .ver { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; }
  .ver.current { border-color: var(--ochre); }
  .ver .meta { font-family: var(--mono); font-size: 10.5px; color: var(--muted); margin-top: 3px; }
  .toast {
    position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
    background: var(--iron); color: var(--parchment); padding: 8px 14px; border-radius: 999px;
    font-size: 12.5px; opacity: 0; transition: opacity .2s; pointer-events: none;
  }
  .toast.on { opacity: 1; }
  .tabs { display: flex; gap: 6px; }
  .tabs button.on { border-color: var(--ochre); color: var(--ink-ochre); font-weight: 650; }
</style>
</head>
<body>
<header>
  <div class="mark">T</div>
  <div class="brand">teresis<small id="ver"></small></div>
  <div class="tabs">
    <button id="tabBrowse" class="on">Browse</button>
    <button id="tabSearch">Recall</button>
  </div>
  <input id="q" type="search" placeholder="Search memories…" />
  <select id="scope"><option value="">all scopes</option></select>
  <select id="kind">
    <option value="">all kinds</option>
    <option>fact</option><option>preference</option><option>decision</option>
    <option>procedure</option><option>lesson</option><option>event</option><option>episode</option>
  </select>
  <div class="spacer"></div>
  <div class="stats" id="stats"></div>
</header>
<main>
  <section class="list">
    <div id="rows"></div>
    <div id="entities"></div>
  </section>
  <aside class="detail" id="detail"><div class="empty">Select a memory to inspect it.</div></aside>
</main>
<div class="toast" id="toast"></div>
<script>
const $ = (s) => document.querySelector(s);
let mode = "browse", selected = null;

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 1800);
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (t) => t ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") : "—";

async function loadStats() {
  const s = await api("/api/stats");
  $("#ver").textContent = "v" + s.version;
  $("#stats").innerHTML = ["active","total","superseded","entities","links"]
    .map((k) => `<span><b>${s[k] ?? 0}</b> ${k}</span>`).join("");
  const scopes = await api("/api/scopes");
  const cur = $("#scope").value;
  $("#scope").innerHTML = '<option value="">all scopes</option>' +
    scopes.map((r) => `<option value="${esc(r.scope)}">${esc(r.scope)} (${r.n})</option>`).join("");
  $("#scope").value = cur;
}

function rowHtml(m) {
  const cls = ["row"];
  if (selected === m.id) cls.push("sel");
  const pills = [
    m.kind && `<span class="pill">${esc(m.kind)}</span>`,
    m.pinned && `<span class="pill pinned">pinned</span>`,
    m.superseded_by && `<span class="pill superseded">superseded</span>`,
    m.score != null && `<span class="score">${m.score.toFixed(3)}</span>`,
  ].filter(Boolean).join(" ");
  return `<div class="${cls.join(" ")}" data-id="${esc(m.id)}">
    <div><div class="content">${esc(m.content)}</div>
      <div class="meta">${esc(m.scope)}${m.key ? " · key=" + esc(m.key) : ""} · ${fmt(m.updated_at)}</div></div>
    <div>${pills}</div></div>`;
}

async function loadList() {
  const q = $("#q").value.trim();
  const scope = $("#scope").value;
  const kind = $("#kind").value;
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (scope) p.set("scope", scope);
  if (kind) p.set("kind", kind);
  p.set("limit", q ? "40" : "120");
  const data = await api((q || mode === "search" ? "/api/recall?" : "/api/memories?") + p);
  $("#rows").innerHTML = data.length
    ? data.map(rowHtml).join("")
    : `<div class="empty">No memories${q ? " match “" + esc(q) + "”" : " yet"}.</div>`;
  document.querySelectorAll(".row").forEach((el) =>
    el.addEventListener("click", () => openMemory(el.dataset.id)));
  if (!q) loadEntities();
}

async function loadEntities() {
  const rows = await api("/api/entities?limit=24");
  if (!rows.length) { $("#entities").innerHTML = ""; return; }
  $("#entities").innerHTML = `<h2>Entities</h2><div class="chips">` +
    rows.map((e) => `<span class="chip${e.explicit ? " explicit" : ""}" data-key="${esc(e.key)}" title="${esc(e.kind)} · ${e.memories} memories">${esc(e.name)} <b>${e.memories}</b></span>`).join("") +
    `</div>`;
  document.querySelectorAll(".chip").forEach((el) =>
    el.addEventListener("click", () => { $("#q").value = el.dataset.key; mode = "search"; loadList(); }));
}

async function openMemory(id) {
  selected = id;
  document.querySelectorAll(".row").forEach((el) => el.classList.toggle("sel", el.dataset.id === id));
  const m = await api("/api/memories/" + encodeURIComponent(id));
  const ents = (m.entities || []).map((e) =>
    `<span class="chip${e.explicit ? " explicit" : ""}">${esc(e.name)}</span>`).join("") || '<span style="color:var(--muted)">none</span>';
  const hist = (m.history || []).map((h) => `
    <div class="ver${h.id === m.memory.id ? " current" : ""}">
      ${esc(h.content)}<div class="meta">${h.id === m.memory.id ? "current" : "version"} · ${fmt(h.updated_at)}${h.superseded_at ? " · superseded " + fmt(h.superseded_at) : ""}</div>
    </div>`).join("");
  $("#detail").innerHTML = `
    <div class="chips"><span class="pill">${esc(m.memory.kind)}</span>
      <span class="pill">${esc(m.memory.scope)}</span>
      ${m.memory.pinned ? '<span class="pill pinned">pinned</span>' : ""}</div>
    <p style="font-size:14.5px;margin:10px 0 12px">${esc(m.memory.content)}</p>
    <dl class="kv">
      <dt>id</dt><dd>${esc(m.memory.id)}</dd>
      <dt>key</dt><dd>${esc(m.memory.key || "—")}</dd>
      <dt>source</dt><dd>${esc(m.memory.source || "—")}</dd>
      <dt>importance</dt><dd>${m.memory.importance}</dd>
      <dt>created</dt><dd>${fmt(m.memory.created_at)}</dd>
      <dt>updated</dt><dd>${fmt(m.memory.updated_at)}</dd>
      <dt>accesses</dt><dd>${m.memory.access_count}</dd>
    </dl>
    <h2>Entities</h2><div class="chips">${ents}</div>
    <div class="actions">
      <button id="btnPin">${m.memory.pinned ? "Unpin" : "Pin"}</button>
      <button id="btnEdit">Edit</button>
      <button id="btnForget">Forget</button>
    </div>
    <h2>Versions</h2><div class="history">${hist || '<div class="empty">No versions.</div>'}</div>`;
  $("#btnPin").onclick = async () => {
    await api("/api/memories/" + m.memory.id + "/pin", {method: "POST", body: JSON.stringify({pinned: !m.memory.pinned})});
    toast(m.memory.pinned ? "Unpinned" : "Pinned"); await loadStats(); await openMemory(id); await loadList();
  };
  $("#btnEdit").onclick = async () => {
    const next = prompt("New content (creates a new version):", m.memory.content);
    if (!next || next === m.memory.content) return;
    await api("/api/memories/" + m.memory.id, {method: "POST", body: JSON.stringify({content: next})});
    toast("Saved new version"); await loadStats(); await openMemory(id); await loadList();
  };
  $("#btnForget").onclick = async () => {
    if (!confirm("Soft-delete this memory?")) return;
    await api("/api/memories/" + m.memory.id + "/forget", {method: "POST", body: "{}"});
    toast("Forgotten"); selected = null; $("#detail").innerHTML = '<div class="empty">Select a memory to inspect it.</div>';
    await loadStats(); await loadList();
  };
}

$("#q").addEventListener("input", () => { mode = $("#q").value.trim() ? "search" : "browse"; loadList(); });
$("#scope").addEventListener("change", loadList);
$("#kind").addEventListener("change", loadList);
$("#tabBrowse").onclick = () => { mode = "browse"; $("#q").value = ""; loadList(); };
$("#tabSearch").onclick = () => { mode = "search"; $("#q").focus(); };
loadStats().then(loadList).catch((e) => toast(e.message));
</script>
</body>
</html>
"""


def _json_memory(m) -> dict[str, Any]:
    return m.to_dict(compact=True) if hasattr(m, "to_dict") else dict(m)


def make_handler(store: MemoryStore, token: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"teresis-ui/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
            if os.environ.get("TERESIS_UI_VERBOSE"):
                super().log_message(fmt, *args)

        # -- helpers ------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, code: int = 200) -> None:
            self._send(code, json.dumps(data, default=str).encode(), "application/json; charset=utf-8")

        def _error(self, code: int, msg: str) -> None:
            self._json({"error": msg}, code)

        def _authorized(self) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return header.removeprefix("Bearer ").strip() == token

        def _body(self) -> dict[str, Any]:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                data = json.loads(raw or b"{}")
                return data if isinstance(data, dict) else {}
            except (ValueError, json.JSONDecodeError):
                return {}

        # -- routes -------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    self._send(200, _INDEX.encode(), "text/html; charset=utf-8")
                elif path == "/api/stats":
                    self._json({**store.stats(), "version": __version__})
                elif path == "/api/scopes":
                    rows = store._q(
                        "SELECT scope, count(*) AS n FROM memories WHERE deleted_at IS NULL"
                        " GROUP BY scope ORDER BY n DESC"
                    )
                    self._json([dict(r) for r in rows])
                elif path == "/api/memories":
                    qs = parse_qs(urlparse(self.path).query)
                    scope = (qs.get("scope") or [None])[0]
                    kind = (qs.get("kind") or [None])[0]
                    limit = min(int((qs.get("limit") or ["100"])[0]), 500)
                    where = ["m.deleted_at IS NULL"]
                    params: list[Any] = []
                    if scope:
                        where.append("m.scope = ?")
                        params.append(scope)
                    if kind:
                        where.append("m.kind = ?")
                        params.append(kind)
                    rows = store._q(
                        f"SELECT * FROM memories m WHERE {' AND '.join(where)}"
                        f" ORDER BY m.pinned DESC, m.updated_at DESC LIMIT ?",
                        [*params, limit],
                    )
                    from .store import Memory

                    self._json([_json_memory(Memory.from_row(r)) for r in rows])
                elif path.startswith("/api/memories/"):
                    self._memory_detail(unquote(path.rsplit("/", 1)[-1]))
                elif path == "/api/recall":
                    qs = parse_qs(urlparse(self.path).query)
                    q = (qs.get("q") or [""])[0]
                    scope = (qs.get("scope") or [None])[0]
                    kind = (qs.get("kind") or [None])[0]
                    limit = min(int((qs.get("limit") or ["25"])[0]), 100)
                    mems = store.recall(
                        q, scope=scope or None, k=limit, kinds=[kind] if kind else None, touch=False
                    )
                    self._json([_json_memory(m) for m in mems])
                elif path == "/api/entities":
                    qs = parse_qs(urlparse(self.path).query)
                    limit = min(int((qs.get("limit") or ["50"])[0]), 200)
                    self._json(store.top_entities(limit=limit))
                else:
                    self._error(404, "not found")
            except Exception as exc:  # keep the UI alive on a bad query
                self._error(400, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return self._error(401, "missing or bad TERESIS_UI_TOKEN")
            path = urlparse(self.path).path
            body = self._body()
            try:
                if path.startswith("/api/memories/") and path.endswith("/pin"):
                    mid = unquote(path[len("/api/memories/"):-len("/pin")])
                    res = store.update(mid, pinned=bool(body.get("pinned", True)))
                    return self._json(res.to_dict())
                if path.startswith("/api/memories/") and path.endswith("/forget"):
                    mid = unquote(path[len("/api/memories/"):-len("/forget")])
                    return self._json({"removed": store.forget(mid, hard=bool(body.get("hard")))})
                if path.startswith("/api/memories/"):
                    mid = unquote(path[len("/api/memories/"):])
                    res = store.update(mid, body.get("content"), importance=body.get("importance"))
                    return self._json(res.to_dict())
                if path == "/api/memories":
                    res = store.remember(
                        body.get("content", ""),
                        scope=body.get("scope") or "global",
                        kind=body.get("kind") or "fact",
                        key=body.get("key") or None,
                        importance=float(body.get("importance", 0.5)),
                        pinned=bool(body.get("pinned")),
                        tags=body.get("tags") or (),
                    )
                    return self._json(res.to_dict())
                self._error(404, "not found")
            except (KeyError, ValueError) as exc:
                self._error(400, str(exc))
            except Exception as exc:
                self._error(500, str(exc))

        def _memory_detail(self, mid: str) -> None:
            mem = store.get(mid)
            if mem is None:
                return self._error(404, "no such memory")
            self._json({
                "memory": mem.to_dict(compact=True),
                "entities": store.entities_for(mid),
                "history": [_json_memory(h) for h in store.history(mid)],
            })

    return Handler


def serve(store: MemoryStore, *, host: str = "127.0.0.1", port: int = 7878, open_browser: bool = True) -> None:
    """Serve the inspector until interrupted."""
    token = os.environ.get("TERESIS_UI_TOKEN") or None
    httpd = ThreadingHTTPServer((host, port), make_handler(store, token))
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"teresis ui on {url}  (db: {store.path})", flush=True)
    if token:
        print("TERESIS_UI_TOKEN is set: writes need `Authorization: Bearer <token>`", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
