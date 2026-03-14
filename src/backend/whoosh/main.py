"""
Whoosh search backend for Engram.

Full-text search with field boosting, tag filtering, and relation graph
stored as a separate JSON file. The index is a rebuildable cache on disk.
Whoosh is pure Python — no system dependencies required.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from whoosh.fields import ID, KEYWORD, TEXT, Schema
from whoosh.index import create_in, exists_in, open_dir
from whoosh.qparser import MultifieldParser

from backend import SearchBackend, extract_relations

logger = logging.getLogger("engram")

# ---------------------------------------------------------------------------
# Whoosh schema
# ---------------------------------------------------------------------------

SCHEMA: Schema = Schema(
    id=ID(stored=True, unique=True),
    title=TEXT(stored=False, field_boost=5.0),
    content=TEXT(stored=False),
    tags=KEYWORD(stored=False, commas=True, lowercase=True),
)

# Relations file name within the index directory
RELATIONS_FILE: str = "relations.json"


class WhooshBackend(SearchBackend):
    """
    Whoosh-based search backend with multi-field search.

    Stores a full-text index on disk. The index is a cache — Markdown
    files are the source of truth and can be rebuilt at any time.

    Relations are stored in a separate JSON file alongside the index
    because Whoosh does not support arbitrary term storage like Xapian.

    Args:
        index_path: Path to the Whoosh index directory.
    """

    def __init__(self, index_path: str | Path) -> None:
        """
        Initialize the Whoosh backend.

        Opens an existing index or creates a new one at the given path.

        Args:
            index_path: Path to the Whoosh index directory.

        Errors:
            Creates the directory if missing.
        """

        self._index_path = Path(index_path)
        self._index_path.mkdir(parents=True, exist_ok=True)
        self._relations_path = self._index_path / RELATIONS_FILE

    # -------------------------------------------------------------------
    # Internal index access
    # -------------------------------------------------------------------

    def _get_index(self) -> "whoosh.index.Index":  # noqa: F821
        """
        Open or create the Whoosh index.

        Returns:
            A Whoosh Index instance.
        """

        if exists_in(str(self._index_path)):
            # Open existing index
            return open_dir(str(self._index_path))

        # Create new index
        return create_in(str(self._index_path), SCHEMA)

    # -------------------------------------------------------------------
    # Relation graph (JSON file)
    # -------------------------------------------------------------------

    def _load_relations(self) -> dict[str, list[dict[str, str]]]:
        """
        Load the relation graph from the JSON file.

        Returns:
            Dict mapping entry_id to list of outgoing relations
            (each with 'target' and 'type' keys).
        """

        if not self._relations_path.exists():
            # No relations file yet
            return {}

        try:
            text = self._relations_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read relations file: %s", exc)
            # Corrupted or unreadable
            return {}

        # Loaded
        return data

    def _save_relations(self, relations: dict[str, list[dict[str, str]]]) -> None:
        """
        Save the relation graph to the JSON file.

        Uses write-to-temp-then-rename for atomicity.

        Args:
            relations: Dict mapping entry_id to list of outgoing relations.
        """

        tmp = self._relations_path.with_suffix(".json.tmp")

        try:
            tmp.write_text(
                json.dumps(relations, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.rename(self._relations_path)
        except OSError:
            # Clean up partial temp file
            tmp.unlink(missing_ok=True)
            raise

    # -------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------

    def index(self, entry: dict[str, Any]) -> None:
        """
        Index or update a single entry in Whoosh.

        Args:
            entry: Dict with id, title, tags, content.
        """

        ix = self._get_index()
        writer = ix.writer()
        writer.update_document(
            id=entry["id"],
            title=entry["title"],
            content=entry["content"],
            tags=",".join(entry["tags"]),
        )
        writer.commit()

        # Update relations for this entry
        relations = self._load_relations()
        outgoing = extract_relations(entry["content"])
        if outgoing:
            relations[entry["id"]] = outgoing
        else:
            # Remove entry if no outgoing relations
            relations.pop(entry["id"], None)
        self._save_relations(relations)

        logger.info("Indexed entry %s", entry["id"])

    def unindex(self, entry_id: str) -> None:
        """
        Remove an entry from the Whoosh index.

        Args:
            entry_id: UUID of the entry.
        """

        ix = self._get_index()
        writer = ix.writer()
        writer.delete_by_term("id", entry_id)
        writer.commit()

        # Remove relations for this entry
        relations = self._load_relations()
        if relations.pop(entry_id, None) is not None:
            self._save_relations(relations)

        logger.info("Unindexed entry %s", entry_id)

    def search(
        self, query_str: str, tags: list[str] | None, limit: int
    ) -> list[dict[str, Any]]:
        """
        Full-text search with optional tag filtering.

        Args:
            query_str: Search query string.
            tags: Optional list of normalized tags to filter by (AND logic).
            limit: Maximum number of results.

        Returns:
            List of dicts with id and score keys.
        """

        if not query_str or not query_str.strip():
            # Empty query
            return []

        try:
            ix = self._get_index()
        except Exception:
            logger.warning("Index not found — returning empty results")
            # No index
            return []

        # Multi-field parser searching title and content
        parser = MultifieldParser(["title", "content"], schema=ix.schema)
        query = parser.parse(query_str)

        results: list[dict[str, Any]] = []

        with ix.searcher() as searcher:
            # Apply tag filter if specified
            if tags:
                from whoosh.query import And, Term

                tag_filter = And([Term("tags", t) for t in tags])
                hits = searcher.search(query, filter=tag_filter, limit=limit)
            else:
                hits = searcher.search(query, limit=limit)

            for hit in hits:
                # Convert Whoosh score to a percentage (0-100)
                score = int(min(hit.score * 10, 100))
                results.append({"id": hit["id"], "score": score})

        logger.info("Search '%s' returned %d results", query_str, len(results))
        # Search complete
        return results

    def rebuild(self, entries: list[dict[str, Any]]) -> int:
        """
        Rebuild index from a list of entries.

        Creates a fresh index from scratch, replacing any existing one.

        Args:
            entries: List of dicts with id, title, tags, content.

        Returns:
            Number of entries indexed.
        """

        logger.info("Rebuilding Whoosh index (%d entries)", len(entries))

        # Create a fresh index (overwrites existing)
        ix = create_in(str(self._index_path), SCHEMA)
        writer = ix.writer()

        relations: dict[str, list[dict[str, str]]] = {}
        count = 0

        for entry in entries:
            writer.update_document(
                id=entry["id"],
                title=entry["title"],
                content=entry["content"],
                tags=",".join(entry["tags"]),
            )

            # Collect relations
            outgoing = extract_relations(entry["content"])
            if outgoing:
                relations[entry["id"]] = outgoing

            count += 1

        writer.commit()

        # Save all relations at once
        self._save_relations(relations)

        logger.info("Rebuild complete: %d entries indexed", count)
        # Rebuild done
        return count

    def get_relations(self, entry_id: str) -> dict[str, list[dict[str, str]]]:
        """
        Get outgoing and incoming graph relations for an entry.

        Reads the relation graph from the JSON file and computes both
        outgoing links (from this entry) and incoming backlinks (from
        other entries pointing to this one).

        Args:
            entry_id: UUID of the entry.

        Returns:
            Dict with 'out' and 'in' lists. Each item has 'type' and 'id'.
        """

        out: list[dict[str, str]] = []
        incoming: list[dict[str, str]] = []

        all_relations = self._load_relations()

        # --- Outgoing relations ---
        for rel in all_relations.get(entry_id, []):
            out.append({"type": rel["type"], "id": rel["target"]})

        # --- Incoming relations (backlinks) ---
        for source_id, rels in all_relations.items():
            if source_id == entry_id:
                continue

            for rel in rels:
                if rel["target"] == entry_id:
                    incoming.append({"type": rel["type"], "id": source_id})

        # Relations resolved
        return {"out": out, "in": incoming}
