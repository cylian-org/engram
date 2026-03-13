# MCP KB — Knowledge Base Server

MCP server providing persistent knowledge storage with full-text search. Entries are Markdown files indexed by Xapian.

## Setup

```bash
# System dependency
apt install python3-xapian

# Data directories
mkdir -p /opt/knowledge/entries /opt/knowledge/index/fr

# Virtual environment (system-site-packages for xapian)
python3 -m venv .venv --system-site-packages
.venv/bin/pip install -r requirements.txt
```

## Claude Code registration

In `~/.claude.json` → `mcpServers`:

```json
"kb": {
  "command": "/opt/projects/mcp-kb/.venv/bin/python",
  "args": ["/opt/projects/mcp-kb/server.py", "--data-path", "/opt/knowledge"]
}
```

## Tools

| Tool | Description |
|------|-------------|
| `kb_search` | Full-text search with tag filtering |
| `kb_get` | Read an entry by ID |
| `kb_store` | Create an entry (with duplicate detection) |
| `kb_update` | Partial update of an entry |
| `kb_delete` | Delete an entry |
| `kb_list` | Browse entries by title |
| `kb_tags` | List all tags with counts |
| `kb_rebuild` | Rebuild the search index |

## Entry format

```yaml
---
id: <uuid>
title: Entry Title
tags: [tag1, tag2]
---

Markdown content here...
```
