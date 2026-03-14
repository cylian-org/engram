# Changelog

## 0.2.0

- Renamed project to Engram
- Consolidated tools to 7: remember (upsert), recall, search, list, tags, forget, rebuild
- Graph relations via `kb://uuid#type` links in content (outgoing + incoming backlinks)
- Three transports: stdio, SSE, streamable-http
- Docker support (Alpine image with `cylian/engram`)
- CLI options: `--data-path`, `--log-file`, `--transport`, `--host`, `--port`
- Duplicate detection with title similarity (SequenceMatcher)
- Prepared for open-source release (MIT license, README)

## 0.1.0

- Initial release
- 8 MCP tools: kb_search, kb_get, kb_store, kb_update, kb_delete, kb_list, kb_tags, kb_rebuild
- Markdown files with YAML frontmatter as storage
- Xapian full-text search with French stemming
- Duplicate detection on store
- Tag-based filtering
- stdio transport (Claude Code integration)
