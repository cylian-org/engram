"""
Search backends for Engram.

Defines the SearchBackend interface and shared utilities.
Source of truth remains the Markdown files — backends are rebuildable caches.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

# Regex for extracting kb:// links with optional #type fragment
RE_KB_LINK: re.Pattern[str] = re.compile(
    r"\[[^\]]*\]\(kb://([a-f0-9-]+)(?:#([a-zA-Z0-9_-]+))?\)"
)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class SearchBackend(ABC):
    """
    Abstract search backend interface.

    All backends must implement indexing, unindexing, searching, and
    rebuilding. The backend is a cache — Markdown files are the source
    of truth.
    """

    @abstractmethod
    def index(self, entry: dict[str, Any]) -> None:
        """
        Index or update an entry. Must handle upsert.

        Args:
            entry: Dict with id, title, tags, content.
        """
        ...

    @abstractmethod
    def unindex(self, entry_id: str) -> None:
        """
        Remove an entry from the index.

        Args:
            entry_id: UUID of the entry.
        """
        ...

    @abstractmethod
    def search(
        self, query_str: str, tags: list[str] | None, limit: int
    ) -> list[dict[str, Any]]:
        """
        Full-text search with optional tag filtering.

        Returns lightweight results (id, score) — the caller enriches
        with title, tags, and snippets from the Markdown files.

        Args:
            query_str: Search query string.
            tags: Optional list of normalized tags to filter by (AND logic).
            limit: Maximum number of results.

        Returns:
            List of dicts with id and score keys.
        """
        ...

    @abstractmethod
    def rebuild(self, entries: list[dict[str, Any]]) -> int:
        """
        Rebuild index from a list of entries.

        Args:
            entries: List of dicts with id, title, tags, content.

        Returns:
            Number of entries indexed.
        """
        ...

    @abstractmethod
    def get_relations(self, entry_id: str) -> dict[str, list[dict[str, str]]]:
        """
        Get outgoing and incoming graph relations for an entry.

        Args:
            entry_id: UUID of the entry.

        Returns:
            Dict with 'out' and 'in' lists. Each item has 'type' and 'id'.
        """
        ...


# ---------------------------------------------------------------------------
# Relation extraction (shared utility)
# ---------------------------------------------------------------------------


def extract_relations(content: str) -> list[dict[str, str]]:
    """
    Extract kb:// link relations from Markdown content.

    Parses links of the form [label](kb://uuid) or [label](kb://uuid#type).
    When no #type fragment is present, defaults to "related".

    Args:
        content: Markdown content body.

    Returns:
        List of dicts with 'target' (UUID) and 'type' (relation type).
    """

    relations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in RE_KB_LINK.finditer(content):
        target_id = match.group(1)
        rel_type = match.group(2) or "related"

        # Deduplicate identical target+type pairs
        key = (target_id, rel_type)
        if key in seen:
            continue
        seen.add(key)

        relations.append({"target": target_id, "type": rel_type})

    # Extracted
    return relations
