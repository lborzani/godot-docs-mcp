# godot-docs-mcp

MCP server with the official Godot docs (manual + class reference), full-text indexed with SQLite FTS5. Python stdlib only.

Tools: `search_docs(query, kind?)`, `get_class(name, member?)`, `read_doc(path, offset?)`.

## Deploy (Portainer / Raspberry Pi 5)

Stacks → Add stack → Repository → this repo, compose file `docker-compose.yml`.
Environment variables:

- `MCP_TOKEN` (required): `openssl rand -hex 32`
- `GODOT_DOCS_BRANCH` (optional, default `stable`): e.g. `4.6`

Without Portainer: `MCP_TOKEN=... docker compose up -d --build`

## Connect Claude Code

```bash
claude mcp add --transport http godot-docs http://<pi-ip>:8765/mcp --header "Authorization: Bearer <token>" -s user
```

## Local (stdio)

```bash
python3 server.py --build
claude mcp add godot-docs -s user -- python3 /path/to/server.py
python3 test_server.py   # smoke test (stdio + http)
```

Docs content: [godot-docs](https://github.com/godotengine/godot-docs), CC BY 3.0.
