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
        default="/opt/knowledge",
        help="Root path for knowledge data (default: /opt/knowledge)",
    )
    parser.add_argument(
        "--log-file",
        default="/var/log/mcp-kb.log",
        help="Path to the log file (default: /var/log/mcp-kb.log)",
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

    # File handler (only — stderr is captured by Claude Code in stdio mode)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

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

mcp = FastMCP(name="MCP KB Server")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def kb_search(
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

    logger.info("kb_search: query='%s', tags=%s, limit=%d", query, tags, limit)

    results = kb.search(query, tags=tags, limit=limit)

    # Search done
    return {"count": len(results), "results": results}


@mcp.tool()
def kb_get(entry_id: str) -> dict:
    """
    Read the full content of a knowledge base entry.

    Args:
        entry_id: UUID of the entry.

    Returns:
        Dict with id, title, tags, content — or error if not found.
    """

    logger.info("kb_get: id=%s", entry_id)

    entry = kb.get(entry_id)
    if not entry:
        # Not found
        return {"error": f"Entry {entry_id} not found"}

    # Entry retrieved
    return entry


@mcp.tool()
def kb_store(
    title: str,
    content: str,
    tags: list[str],
    force: bool = False,
) -> dict:
    """
    Create a new knowledge base entry.

    Blocks if a duplicate title is detected (similar existing entry).
    Use force=True to bypass duplicate check.

    Args:
        title: Entry title.
        content: Entry body (Markdown).
        tags: List of tags for categorization.
        force: Skip duplicate detection (default: False).

    Returns:
        Dict with id on success, or error with duplicates list on conflict.
    """

    logger.info("kb_store: title='%s', tags=%s, force=%s", title, tags, force)

    result = kb.store(title, content, tags, force=force)

    # Store done
    return result


@mcp.tool()
def kb_update(
    entry_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """
    Update an existing knowledge base entry.

    Only provided fields are changed. Tags are fully replaced if provided.

    Args:
        entry_id: UUID of the entry to update.
        title: New title (optional).
        content: New content (optional).
        tags: New tags — replaces existing tags entirely (optional).

    Returns:
        Dict with success status or error if not found.
    """

    logger.info(
        "kb_update: id=%s, title=%s, tags=%s",
        entry_id,
        title is not None,
        tags is not None,
    )

    success = kb.update(entry_id, title=title, content=content, tags=tags)
    if not success:
        # Not found
        return {"error": f"Entry {entry_id} not found"}

    # Updated
    return {"success": True, "id": entry_id}


@mcp.tool()
def kb_delete(entry_id: str) -> dict:
    """
    Delete a knowledge base entry (file and index).

    Args:
        entry_id: UUID of the entry to delete.

    Returns:
        Dict with success status or error if not found.
    """

    logger.info("kb_delete: id=%s", entry_id)

    success = kb.delete(entry_id)
    if not success:
        # Not found
        return {"error": f"Entry {entry_id} not found"}

    # Deleted
    return {"success": True, "id": entry_id}


@mcp.tool()
def kb_list(
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

    logger.info("kb_list: tags=%s, limit=%d", tags, limit)

    entries = kb.list_entries(tags=tags, limit=limit)

    # Listed
    return {"count": len(entries), "entries": entries}


@mcp.tool()
def kb_tags() -> dict:
    """
    List all tags in the knowledge base with entry counts.

    Returns:
        Dict with tags list (tag, count), sorted by count descending.
    """

    logger.info("kb_tags")

    tags = kb.list_tags()

    # Tags listed
    return {"count": len(tags), "tags": tags}


@mcp.tool()
def kb_rebuild() -> dict:
    """
    Rebuild the Xapian search index from Markdown files.

    Deletes the existing index and reindexes all entries. Use this
    if the index is corrupted or after manual file changes.

    Returns:
        Dict with number of entries indexed.
    """

    logger.info("kb_rebuild: starting full rebuild")

    count = kb.rebuild()

    logger.info("kb_rebuild: complete — %d entries", count)
    # Rebuild done
    return {"success": True, "entries_indexed": count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting MCP KB Server (stdio transport)")
    mcp.run(transport="stdio")
