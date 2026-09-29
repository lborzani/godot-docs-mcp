#!/usr/bin/env python3
"""MCP server (stdlib only) exposing the official Godot docs.

  python3 server.py --build   # clone godot-docs + build SQLite FTS5 index
  python3 server.py           # run MCP server on stdio
  python3 server.py --http    # run MCP server over Streamable HTTP (POST /mcp)

HTTP env: MCP_HOST (0.0.0.0), MCP_PORT (8765), MCP_TOKEN (bearer token; strongly recommended),
MCP_ALLOWED_ORIGINS (comma list; requests with any other Origin header are rejected).
"""
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "data" / "godot-docs"
DB = ROOT / "data" / "index.db"
BRANCH = os.environ.get("GODOT_DOCS_BRANCH", "stable")
REPO = "https://github.com/godotengine/godot-docs"
SKIP_DIRS = {"_build", "_extensions", "_static", "_templates", "_tools", ".git"}


# ---------- RST -> readable text ----------

ROLE_WITH_TARGET = re.compile(r":[\w:-]+:`([^`<]*?)\s*<[^>]*>`")
ROLE = re.compile(r":[\w:-]+:`([^`]*)`")
EXT_LINK = re.compile(r"`([^`<]+?)\s*<(https?://[^>]+)>`__?")
SUBST = re.compile(r"\|(\w+)\|")
NOISE = re.compile(r"^\s*(\.\. rst-class::|\.\. table::|:widths:|:github_url:|\.\. DO NOT EDIT|\.\. Generat|\.\. XML source|\+[-=+]+\+\s*$)")


def clean(rst: str) -> str:
    out = []
    for line in rst.splitlines():
        if NOISE.match(line):
            continue
        line = line.replace("🔗", "")
        line = ROLE_WITH_TARGET.sub(r"\1", line)
        line = ROLE.sub(r"\1", line)
        line = EXT_LINK.sub(r"\1 (\2)", line)
        line = SUBST.sub(r"\1", line)
        line = line.replace("\\ ", "")
        if re.match(r"^\s*\|.*\|\s*$", line):  # grid-table row -> "a | b | c"
            line = " | ".join(c.strip() for c in line.strip().strip("|").split("|") if c.strip())
        out.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def title_of(rst: str, fallback: str) -> str:
    lines = rst.splitlines()
    for a, b in zip(lines, lines[1:]):
        if a.strip() and re.fullmatch(r"([=\-*~^#])\1{2,}", b.strip()) and not re.fullmatch(r"[=\-*~^#]+", a.strip()):
            return a.strip()
    return fallback


def build():
    if not DOCS.exists():
        subprocess.run(["git", "clone", "--depth", "1", "-b", BRANCH, REPO, str(DOCS)], check=True)
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE VIRTUAL TABLE docs USING fts5(path UNINDEXED, kind UNINDEXED, title, body)")
    n = 0
    for f in sorted(DOCS.rglob("*.rst")):
        rel = f.relative_to(DOCS)
        if SKIP_DIRS & set(rel.parts):
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        kind = "class" if rel.parts[0] == "classes" else "manual"
        con.execute("INSERT INTO docs VALUES (?,?,?,?)", (rel.as_posix(), kind, title_of(raw, rel.stem), clean(raw)))
        n += 1
    con.commit()
    print(f"indexed {n} pages from {BRANCH} -> {DB}", file=sys.stderr)


# ---------- tools ----------

def url(path: str) -> str:
    return f"https://docs.godotengine.org/en/{BRANCH}/{path[:-4]}.html"


def fts_query(q: str, op: str) -> str:
    words = [re.sub(r'[^\w.@]', "", w) for w in q.split()]
    return f" {op} ".join(f'"{w}"' for w in words if w)


def search_docs(query: str, kind: str = "all", limit: int = 8) -> str:
    con = sqlite3.connect(DB)
    sql = ("SELECT path, title, snippet(docs, 3, '[', ']', '…', 24) FROM docs WHERE docs MATCH ?"
           + ("" if kind == "all" else " AND kind = ?") + " ORDER BY bm25(docs, 0, 0, 10, 1) LIMIT ?")
    rows = []
    for op in ("AND", "OR"):  # precise first, then broaden
        q = fts_query(query, op)
        if not q:
            return "Empty query."
        rows = con.execute(sql, (q, limit) if kind == "all" else (q, kind, limit)).fetchall()
        if rows:
            break
    if not rows:
        return f"No results for {query!r}."
    return "\n\n".join(f"## {t}\npath: {p}\nurl: {url(p)}\n{s}" for p, t, s in rows)


def read_doc(path: str, offset: int = 0, max_chars: int = 20000) -> str:
    row = sqlite3.connect(DB).execute("SELECT title, body FROM docs WHERE path = ?", (path,)).fetchone()
    if not row:
        return f"Page not found: {path}. Use search_docs to find valid paths."
    body = row[1]
    chunk = body[offset:offset + max_chars]
    more = f"\n\n[truncated: {len(body)} chars total; call again with offset={offset + max_chars}]" if offset + max_chars < len(body) else ""
    return f"# {row[0]}\nurl: {url(path)}\n\n{chunk}{more}"


def get_class(name: str, member: str = "", offset: int = 0) -> str:
    path = f"classes/class_{name.lower()}.rst"
    if not member:
        return read_doc(path, offset)
    row = sqlite3.connect(DB).execute("SELECT body FROM docs WHERE path = ?", (path,)).fetchone()
    if not row:
        return f"Class not found: {name}."
    m = re.search(rf"^\.\. _class_{re.escape(name)}_\w+?_{re.escape(member)}:$(.*?)(?=^\.\. _|^----$|\Z)",
                  row[0], re.M | re.S | re.I)
    if not m:
        return f"Member {member!r} not found in {name}. Call get_class without member to see the full page."
    return f"{name}.{member}\nurl: {url(path)}\n{m.group(1).strip()}"


TOOLS = {
    "search_docs": (search_docs, "Full-text search over the official Godot docs (manual, tutorials and class reference). "
                    "Returns titles, paths and snippets. Use this first for any Godot question.",
                    {"query": {"type": "string", "description": "Keywords, e.g. 'CharacterBody2D move_and_slide' or 'autoload singleton'"},
                     "kind": {"type": "string", "enum": ["all", "class", "manual"], "default": "all"},
                     "limit": {"type": "integer", "default": 8}}, ["query"]),
    "read_doc": (read_doc, "Read a full docs page by path (from search_docs). Long pages are paginated with offset.",
                 {"path": {"type": "string", "description": "e.g. tutorials/scripting/singletons_autoload.rst"},
                  "offset": {"type": "integer", "default": 0},
                  "max_chars": {"type": "integer", "default": 20000}}, ["path"]),
    "get_class": (get_class, "Godot class reference (API). Without member: full page (inheritance, properties, methods, signals). "
                  "With member: just that method/property/signal/constant/enum.",
                  {"name": {"type": "string", "description": "Class name, e.g. Node2D"},
                   "member": {"type": "string", "description": "Optional member, e.g. move_and_slide"},
                   "offset": {"type": "integer", "default": 0}}, ["name"]),
}

INSTRUCTIONS = (f"Official Godot Engine documentation ({BRANCH}). For any Godot/GDScript question, ground answers "
                "here: search_docs to locate pages, get_class for exact API signatures, read_doc for tutorials. "
                "Prefer these over memory; Godot 3 and 4 APIs differ a lot.")


def handle(msg: dict):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "godot-docs", "version": "1.0.0"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d,
                           "inputSchema": {"type": "object", "properties": p, "required": r}}
                          for n, (_, d, p, r) in TOOLS.items()]}
    if method == "tools/call":
        fn = TOOLS.get(params.get("name"), (None,))[0]
        if not fn:
            raise LookupError(f"Unknown tool {params.get('name')}")
        try:
            return {"content": [{"type": "text", "text": fn(**(params.get("arguments") or {}))}]}
        except Exception as e:  # tool errors go back to the model, not the protocol
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    raise LookupError(f"Method not found: {method}")


def dispatch(msg: dict):
    """JSON-RPC message -> reply dict, or None for notifications."""
    if "id" not in msg:
        return None
    try:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
    except LookupError as e:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": str(e)}}


def serve_stdio():
    for line in sys.stdin:
        if line.strip() and (reply := dispatch(json.loads(line))):
            print(json.dumps(reply), flush=True)


def serve_http():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    token = os.environ.get("MCP_TOKEN", "")
    origins = {o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    host, port = os.environ.get("MCP_HOST", "0.0.0.0"), int(os.environ.get("MCP_PORT", "8765"))

    class H(BaseHTTPRequestHandler):
        def send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # no server->client SSE stream; health check on /health
            self.send(200, b"ok", "text/plain") if self.path == "/health" else self.send(405)

        def do_POST(self):
            if self.path != "/mcp":
                return self.send(404)
            origin = self.headers.get("Origin")
            if origin and origin not in origins:  # DNS-rebinding protection (MCP spec)
                return self.send(403)
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                return self.send(401)
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= 1_000_000:
                return self.send(413)
            try:
                msg = json.loads(self.rfile.read(size))
            except ValueError:
                return self.send(400, json.dumps({"jsonrpc": "2.0", "id": None,
                                                  "error": {"code": -32700, "message": "Parse error"}}).encode())
            if isinstance(msg, list):  # batch (older protocol versions)
                replies = [r for r in map(dispatch, msg) if r]
            else:
                replies = dispatch(msg)
            self.send(200, json.dumps(replies).encode()) if replies else self.send(202)

    if not token:
        print("WARNING: MCP_TOKEN not set, server is open to anyone who can reach it", file=sys.stderr)
    print(f"MCP HTTP on http://{host}:{port}/mcp", file=sys.stderr)
    ThreadingHTTPServer((host, port), H).serve_forever()


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    elif not DB.exists():
        sys.exit(f"Index missing: run `python3 {__file__} --build` first.")
    else:
        serve_http() if "--http" in sys.argv else serve_stdio()
