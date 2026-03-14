"""
MCP KB Server — persistent knowledge base with full-text search.

Provides MCP tools for storing, searching, and managing knowledge entries.
Entries are Markdown files with YAML frontmatter, indexed by Xapian with
French stemming for full-text search.

Transport: stdio (stdin/stdout for MCP protocol, managed by Claude Code).
Data: Markdown files in --data-path/entries/, Xapian index in --data-path/index/fr/.
Logging: All operations logged to /var/log/mcp-kb.log.
"""

from __future__ import annotations

import argparse
import logging

from mcp.server.fastmcp import FastMCP

from database import KnowledgeBase

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace with data-path and log-file.
    """

    parser = argparse.ArgumentParser(description="MCP KB Server (stdio)")
    parser.add_argument(
        "--data-path",
        default="/knowledge",
        help="Root path for knowledge data (default: /knowledge)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to the log file (default: stderr)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Listen address for SSE/HTTP transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8192,
        help="Listen port for SSE/HTTP transport (default: 8192)",
    )

    # Parsed arguments
    return parser.parse_args()


args = parse_args()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_file: str) -> logging.Logger:
    """
    Configure the application logger.

    Sets up file-only logging (stdout/stdin are reserved for MCP stdio
    transport). Uses a consistent format with timestamps.

    Args:
        log_file: Path to the log file.

    Returns:
        Configured logger instance.

    Errors:
        Raises if the log file cannot be opened (no fallback in stdio mode).
    """

    log = logging.getLogger("mcp-kb")
    log.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_file:
        # File handler (explicit path)
        handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        # Stderr handler (default)
        handler = logging.StreamHandler()

    handler.setFormatter(formatter)
    log.addHandler(handler)

    # Logger configured
    return log


logger = setup_logging(args.log_file)

# ---------------------------------------------------------------------------
# Knowledge base initialization
# ---------------------------------------------------------------------------

logger.info("Initializing knowledge base from %s", args.data_path)
kb = KnowledgeBase(args.data_path)
logger.info("Knowledge base ready")

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(name="MCP KB Server", host=args.host, port=args.port)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search(
    query: str,
    tags: list[str] | None = None,
    limit: int = 10,
) -> dict:
    """
    Search the knowledge base using full-text search.

    Uses Xapian with French stemming. Supports wildcards and spelling
    correction. Results ranked by relevance.

    Args:
        query: Search query string.
        tags: Optional tag filter (AND logic — all tags must match).
        limit: Maximum results to return (default: 10).

    Returns:
        Dict with results list (id, title, tags, snippet, score).
    """

    logger.info("search: query='%s', tags=%s, limit=%d", query, tags, limit)

    results = kb.search(query, tags=tags, limit=limit)

    # Search done
    return {"count": len(results), "results": results}


@mcp.tool()
def recall(entry_id: str) -> dict:
    """
    Read the full content of a knowledge base entry.

    Also returns graph relations: outgoing links (from kb://uuid#type
    in content) and incoming backlinks (other articles linking here).

    Args:
        entry_id: UUID of the entry.

    Returns:
        Dict with id, title, tags, content, relations — or error if not found.
        Relations has 'out' and 'in' lists, each with type, id, title.
    """

    logger.info("recall: id=%s", entry_id)

    entry = kb.get(entry_id, with_relations=True)
    if not entry:
        # Not found
        return {"error": f"Entry {entry_id} not found"}

    # Entry retrieved
    return entry


@mcp.tool()
def remember(
    title: str,
    content: str,
    tags: list[str],
    entry_id: str | None = None,
    force: bool = False,
) -> dict:
    """
    Store or update a knowledge base entry (upsert).

    Resolution order:
    1. If entry_id is provided → update that entry
    2. If no entry_id → search for similar titles
       - If a match is found → update the best match
       - If no match → create a new entry
    3. If force=True → always create new (skip duplicate detection)

    Content may contain links to other entries using the format
    [label](kb://uuid#type) where type is the relation kind (e.g.
    runs-on, depends-on, mirrors). These links are automatically
    indexed as graph relations, queryable via recall.

    Args:
        title: Entry title.
        content: Entry body (Markdown).
        tags: List of tags for categorization.
        entry_id: Optional UUID of an existing entry to update.
        force: Skip duplicate detection and always create new.

    Returns:
        Dict with id, title, and action ('created' or 'updated').
    """

    logger.info(
        "remember: title='%s', tags=%s, entry_id=%s, force=%s",
        title,
        tags,
        entry_id,
        force,
    )

    result = kb.remember(title, content, tags, entry_id=entry_id, force=force)

    # Remember done
    return result


@mcp.tool()
def forget(entry_id: str) -> dict:
    """
    Delete a knowledge base entry (file and index).

    Args:
        entry_id: UUID of the entry to delete.

    Returns:
        Dict with success status or error if not found.
    """

    logger.info("forget: id=%s", entry_id)

    success = kb.delete(entry_id)
    if not success:
        # Not found
        return {"error": f"Entry {entry_id} not found"}

    # Forgotten
    return {"success": True, "id": entry_id}


@mcp.tool()
def list(
    tags: list[str] | None = None,
    limit: int = 50,
) -> dict:
    """
    List knowledge base entries, sorted by title.

    Args:
        tags: Optional tag filter (AND logic — all tags must match).
        limit: Maximum entries to return (default: 50).

    Returns:
        Dict with entries list (id, title, tags).
    """

    logger.info("list: tags=%s, limit=%d", tags, limit)

    entries = kb.list_entries(tags=tags, limit=limit)

    # Listed
    return {"count": len(entries), "entries": entries}


@mcp.tool()
def tags() -> dict:
    """
    List all tags in the knowledge base with entry counts.

    Returns:
        Dict with tags list (tag, count), sorted by count descending.
    """

    logger.info("tags")

    tag_list = kb.list_tags()

    # Tags listed
    return {"count": len(tag_list), "tags": tag_list}


@mcp.tool()
def rebuild() -> dict:
    """
    Rebuild the Xapian search index from Markdown files.

    Deletes the existing index and reindexes all entries. Use this
    if the index is corrupted or after manual file changes.

    Returns:
        Dict with number of entries indexed.
    """

    logger.info("rebuild: starting full rebuild")

    count = kb.rebuild()

    logger.info("rebuild: complete — %d entries", count)
    # Rebuild done
    return {"success": True, "entries_indexed": count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting MCP KB Server (%s transport)", args.transport)
    mcp.run(transport=args.transport)
