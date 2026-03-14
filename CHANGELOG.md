# Changelog

## 0.5.0

- `recall` now returns `size` (bytes) and `last_modified` (date) fields
- `remember` now returns `size` (bytes) and a `warnings` list when article content exceeds 2 KB (soft) or 4 KB (hard) thresholds
- Added 4 usage examples to README (store, search, graph, multi-agent)
- Added "Prompt Your Agent" section to README with system prompt template

## 0.4.2

- README rewritten for v0.4.0 (Docker-only development, cleaner transport blocks, Custom Backend section with SearchBackend ABC + Whoosh example)

## 0.4.1

- Removed Whoosh backend (server-side coverage increased, deps simplified)
- Removed `--log-file` option — logs always go to stderr (`docker logs`)
- Added CI coverage report with 80% minimum threshold
- Fixed tool descriptions: "configurable stemming" instead of "French stemming"

## 0.4.0

- Pluggable search backends: `xapian` (default), `sqlite` (FTS5), `whoosh` (pure Python)
- Backend loaded dynamically via `importlib` — any `backend/<name>/main.py` works
- All CLI options have `ENGRAM_*` environment variable fallbacks
- `ENGRAM_*` env vars baked into Docker image as defaults
- Source code moved to `src/` directory

## 0.3.0

- Metadata cache (`_meta_cache`) in `KnowledgeBase` — powers `list`, `tags`, `find_similar`
- Security: path traversal protection (UUID regex), limit clamping, atomic file writes, non-root Docker user
- Best practice guidance added to `remember` tool description
- GitHub mirror excludes `ci/` and `CLAUDE.md`

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
