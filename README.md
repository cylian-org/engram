# Engram -- Persistent Knowledge Base MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server for persistent knowledge management with Xapian full-text search and graph relations.

## Features

- **Markdown files as source of truth** -- the Xapian index is a rebuildable cache
- **Full-text search** with French stemming (Xapian)
- **7 tools**: remember (upsert), recall, search, list, tags, forget, rebuild
- **Graph relations** via `kb://uuid#type` links in content
- **Duplicate detection** based on title similarity
- **Three transports**: stdio, SSE, streamable-http
- **Docker-ready** (Alpine image)

## Quick Start

```bash
# stdio (Claude Code, ChatGPT, etc.)
docker run -i -v ./knowledge:/knowledge cylian/engram

# SSE (network)
docker run -p 8192:8192 -v ./knowledge:/knowledge cylian/engram --transport sse

# HTTP
docker run -p 8192:8192 -v ./knowledge:/knowledge cylian/engram --transport streamable-http
```

## Configuration

### Claude Code (stdio)

Add to your Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "kb": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "./knowledge:/knowledge", "cylian/engram"]
    }
  }
}
```

### SSE (network)

Start the server, then configure your client:

```json
{
  "mcpServers": {
    "kb": {
      "type": "sse",
      "url": "http://127.0.0.1:8192/sse"
    }
  }
}
```

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `remember` | Create or update an entry (upsert) | `title`, `content`, `tags`, `entry_id` (optional), `force` (optional) |
| `recall` | Read full content of an entry with relations | `entry_id` |
| `search` | Full-text search with optional tag filter | `query`, `tags` (optional), `limit` (optional) |
| `list` | List entries sorted by title | `tags` (optional), `limit` (optional) |
| `tags` | List all tags with entry counts | -- |
| `forget` | Delete an entry (file and index) | `entry_id` |
| `rebuild` | Rebuild the Xapian index from files | -- |

## Graph Relations

Entries can reference each other using `kb://uuid#type` links in their Markdown content. The `#type` fragment defines the relation kind (e.g., `runs-on`, `depends-on`, `mirrors`). If omitted, it defaults to `related`.

### Example content

```markdown
This service runs on [pmx-0102](kb://a1b2c3d4-e5f6-7890-abcd-ef1234567890#runs-on)
and depends on [PostgreSQL](kb://f9e8d7c6-b5a4-3210-fedc-ba9876543210#depends-on).
```

### What `recall` returns

When you recall an entry, the `relations` field contains both directions:

- **`out`** -- outgoing links from this entry (e.g., `runs-on`, `depends-on`)
- **`in`** -- incoming backlinks from other entries pointing here

Each relation includes `type`, `id`, and `title`.

## Storage Format

Entries are Markdown files with YAML frontmatter, stored in `<data-path>/entries/`:

```yaml
---
id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
title: Entry Title
tags: [infrastructure, postgresql]
---

Markdown content here...
```

The Xapian index lives in `<data-path>/index/fr/` and can be fully rebuilt from the Markdown files at any time using the `rebuild` tool.

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--data-path` | `/knowledge` | Root path for knowledge data |
| `--log-file` | stderr | Path to the log file |
| `--transport` | `stdio` | MCP transport: `stdio`, `sse`, or `streamable-http` |
| `--host` | `0.0.0.0` | Listen address for SSE/HTTP transport |
| `--port` | `8192` | Listen port for SSE/HTTP transport |

## Development

```bash
# Install
python3 -m venv .venv --system-site-packages
.venv/bin/pip install -r requirements.txt

# Test
.venv/bin/python -m pytest tests/ -v

# Lint
.venv/bin/python -m ruff check .
```

## License

[MIT](LICENSE)
