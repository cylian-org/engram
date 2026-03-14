# Engram — Persistent Knowledge Base MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI agents persistent memory. Markdown files as source of truth, pluggable search backends, typed graph relations.

**Website:** [engram-kb.org](https://engram-kb.org) · **Docker Hub:** [cylian/engram](https://hub.docker.com/r/cylian/engram)

## Quick Start

```bash
docker pull cylian/engram:latest
```

### stdio

Your agent manages the server. Recommended for Claude Code, ChatGPT Desktop, Cursor.

```bash
claude mcp add --transport stdio engram -- \
  docker run -i --rm -v ./knowledge:/knowledge cylian/engram
```

### SSE

Persistent server on the network. Share a KB across multiple agents.

```bash
docker run -d --name engram -p 8192:8192 -v ./knowledge:/knowledge cylian/engram --transport sse
claude mcp add --transport sse engram http://your-host:8192/sse
```

### HTTP

Stateless, load-balanceable.

```bash
docker run -d --name engram -p 8192:8192 -v ./knowledge:/knowledge cylian/engram --transport streamable-http
claude mcp add --transport http engram http://your-host:8192/mcp
```

## Search Backends

Two backends ship out of the box. Switch with `--backend` or `ENGRAM_BACKEND`:

| Backend | Default | Description |
|---------|---------|-------------|
| `xapian` | ✓ | Fast full-text search with configurable stemming |
| `sqlite` | | SQLite FTS5 — query your index with standard SQL tools |

The backend is pluggable: drop a `backend/{name}/main.py` with a `SearchBackend` subclass and it's available automatically.

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `remember` | Create or update an entry (upsert with duplicate detection) | `title`, `content`, `tags`, `entry_id`, `force` |
| `recall` | Read an entry with its graph relations (outgoing + backlinks) | `entry_id` |
| `search` | Full-text search with optional tag filter | `query`, `tags`, `limit` |
| `list` | Browse entries sorted by title | `tags`, `limit` |
| `tags` | List all tags with entry counts | — |
| `forget` | Delete an entry (file and index) | `entry_id` |
| `rebuild` | Rebuild search index from Markdown files | — |

## Graph Relations

Link entries with `kb://uuid#type` URLs in Markdown content:

```markdown
This service runs on [Saturn](kb://a1b2c3d4-...#runs-on)
and depends on [PostgreSQL](kb://f9e8d7c6-...#depends-on).
```

`recall` returns both directions:

```json
{
  "id": "a1b2c3d4-...",
  "title": "My API Service",
  ...
  "relations": {
    "out": [{"type": "runs-on", "id": "e5f6...", "title": "Saturn"}],
    "in": [{"type": "depends-on", "id": "b7c8...", "title": "Frontend App"}]
  }
}
```

Like [HATEOAS](https://en.wikipedia.org/wiki/HATEOAS) for knowledge — every response carries the links to navigate the graph.

## Configuration

All options have `ENGRAM_*` environment variable fallbacks. CLI args take priority.

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--data-path` | `ENGRAM_DATA_PATH` | `/knowledge` | Root path for knowledge data |
| `--backend` | `ENGRAM_BACKEND` | `xapian` | Search backend |
| `--language` | `ENGRAM_LANGUAGE` | `en` | Stemmer language |
| `--transport` | `ENGRAM_TRANSPORT` | `stdio` | MCP transport |
| `--host` | `ENGRAM_HOST` | `0.0.0.0` | Listen address (SSE/HTTP) |
| `--port` | `ENGRAM_PORT` | `8192` | Listen port (SSE/HTTP) |

## Storage Format

Entries are Markdown files with YAML frontmatter in `<data-path>/entries/`:

```yaml
---
id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
title: Entry Title
tags: [infrastructure, postgresql]
---

Markdown content here...
```

The search index is a rebuildable cache in `<data-path>/index/<backend>/`. Delete it and `rebuild` — no data is ever lost.

## Development

```bash
# Install
python3 -m venv .venv --system-site-packages
.venv/bin/pip install -r src/requirements.txt

# Test (89 tests, 90% coverage)
.venv/bin/python -m pytest tests/ -v

# Lint
.venv/bin/python -m ruff check src/ tests/
```

## License

[MIT](LICENSE)
