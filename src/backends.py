"""
Search backends for Engram.

Defines the SearchBackend interface and concrete implementations.
Source of truth remains the Markdown files — backends are rebuildable caches.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import xapian

logger = logging.getLogger("engram")

# ---------------------------------------------------------------------------
# Xapian prefix constants
# ---------------------------------------------------------------------------

PREFIX_ID: str = "Q"
PREFIX_TITLE: str = "XTITLE"
PREFIX_TAG: str = "XTAG"
PREFIX_RELOUT: str = "XRELOUT:"
PREFIX_RELTGT: str = "XRELTGT:"

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
        self, query: str, tags: list[str] | None, limit: int
    ) -> list[dict[str, Any]]:
        """
        Full-text search. Returns list of dicts with id, score.

        Does NOT return content — caller reads from file.

        Args:
            query: Search query string.
            tags: Optional tag filter (AND logic).
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
            Dict with 'out' and 'in' lists. Each item has 'type' and 'id'
            keys — the caller resolves titles.
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


# ---------------------------------------------------------------------------
# Xapian backend
# ---------------------------------------------------------------------------


class XapianBackend(SearchBackend):
    """
    Xapian-based search backend with French stemming.

    Stores a full-text index on disk. The index is a cache — Markdown
    files are the source of truth and can be rebuilt at any time.

    Args:
        index_path: Path to the Xapian index directory.
    """

    def __init__(self, index_path: str | Path) -> None:
        """
        Initialize the Xapian backend.

        Args:
            index_path: Path to the Xapian index directory.

        Errors:
            Creates the directory if missing.
        """

        self._index_path = Path(index_path)
        self._index_path.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------
    # Internal database access
    # -------------------------------------------------------------------

    def _get_writable_db(self) -> xapian.WritableDatabase:
        """
        Open the Xapian database for writing.

        Returns:
            A WritableDatabase instance.
        """

        # Open writable database
        return xapian.WritableDatabase(str(self._index_path), xapian.DB_CREATE_OR_OPEN)

    def _get_readable_db(self) -> xapian.Database:
        """
        Open the Xapian database for reading.

        Returns:
            A Database instance.

        Errors:
            Raises DatabaseOpeningError if the index does not exist.
        """

        # Open read-only database
        return xapian.Database(str(self._index_path))

    # -------------------------------------------------------------------
    # Internal indexing
    # -------------------------------------------------------------------

    def _index_entry_with_db(
        self, entry: dict[str, Any], db: xapian.WritableDatabase
    ) -> None:
        """
        Index or update an entry in a pre-opened Xapian database.

        Builds a Xapian document with title, tags, content, and relation
        terms, then upserts it via replace_document with Q<uuid> as the
        unique ID term.

        Does NOT commit or close the database — the caller is responsible.

        Args:
            entry: Dict with id, title, tags, content.
            db: An already-open WritableDatabase instance.
        """

        doc = xapian.Document()

        # Term generator with French stemmer
        tg = xapian.TermGenerator()
        tg.set_stemmer(xapian.Stem("fr"))
        tg.set_database(db)
        tg.set_flags(tg.FLAG_SPELLING)
        tg.set_document(doc)

        # Index title with higher weight (wdf_inc=5)
        tg.index_text(entry["title"], 5, PREFIX_TITLE)
        # Also index title without prefix for general search
        tg.index_text(entry["title"], 5)

        # Index tags
        for tag in entry["tags"]:
            doc.add_boolean_term(f"{PREFIX_TAG}{tag}")
            # Also index tag text for general search
            tg.index_text(tag, 1)

        # Index content
        tg.increase_termpos()
        tg.index_text(entry["content"], 1)

        # Index outgoing relations from kb:// links in content
        relations = extract_relations(entry["content"])
        for rel in relations:
            # Outgoing relation term: allows reading this entry's outgoing links
            doc.add_boolean_term(f"{PREFIX_RELOUT}{rel['type']}:{rel['target']}")
            # Target marker term: allows finding all entries that link TO a target
            doc.add_boolean_term(f"{PREFIX_RELTGT}{rel['target']}")

        # Store data for retrieval (entry id)
        doc.set_data(entry["id"])

        # Unique ID term for upsert
        id_term = f"{PREFIX_ID}{entry['id']}"
        doc.add_boolean_term(id_term)
        db.replace_document(id_term, doc)

        logger.info("Indexed entry %s", entry["id"])

    # -------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------

    def index(self, entry: dict[str, Any]) -> None:
        """
        Index or update a single entry in Xapian.

        Opens a WritableDatabase, indexes the entry, commits, and closes.
        For bulk operations, use rebuild() instead.

        Args:
            entry: Dict with id, title, tags, content.
        """

        db = self._get_writable_db()
        self._index_entry_with_db(entry, db)

        # Explicit commit to ensure changes are visible to subsequent reads
        db.commit()
        db.close()

    def unindex(self, entry_id: str) -> None:
        """
        Remove an entry from the Xapian index.

        Args:
            entry_id: UUID of the entry.
        """

        db = self._get_writable_db()
        id_term = f"{PREFIX_ID}{entry_id}"
        db.delete_document(id_term)
        # Explicit commit to ensure changes are visible to subsequent reads
        db.commit()
        db.close()
        logger.info("Unindexed entry %s", entry_id)

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

        try:
            db = self._get_readable_db()
        except xapian.DatabaseOpeningError:
            logger.warning("Index not found — returning empty results")
            # No index
            return []

        # Query parser with French stemmer
        qp = xapian.QueryParser()
        qp.set_stemmer(xapian.Stem("fr"))
        qp.set_stemming_strategy(qp.STEM_SOME)
        qp.set_database(db)

        # Allow prefix searches
        qp.add_prefix("title", PREFIX_TITLE)
        qp.add_prefix("tag", PREFIX_TAG)

        flags = qp.FLAG_DEFAULT | qp.FLAG_SPELLING_CORRECTION | qp.FLAG_WILDCARD
        query = qp.parse_query(query_str, flags)

        # Apply tag filter if specified
        if tags:
            tag_queries = [xapian.Query(f"{PREFIX_TAG}{t}") for t in tags]
            tag_query = xapian.Query(xapian.Query.OP_AND, tag_queries)
            query = xapian.Query(xapian.Query.OP_FILTER, query, tag_query)

        enquire = xapian.Enquire(db)
        enquire.set_query(query)

        results: list[dict[str, Any]] = []
        for match in enquire.get_mset(0, limit):
            entry_id = match.document.get_data().decode("utf-8")
            results.append({"id": entry_id, "score": match.percent})

        logger.info("Search '%s' returned %d results", query_str, len(results))
        # Search complete
        return results

    def rebuild(self, entries: list[dict[str, Any]]) -> int:
        """
        Rebuild index from a list of entries.

        Opens a single WritableDatabase with DB_CREATE_OR_OVERWRITE (which
        wipes the existing index) and indexes every entry in one pass.

        Args:
            entries: List of dicts with id, title, tags, content.

        Returns:
            Number of entries indexed.
        """

        logger.info("Rebuilding Xapian index (%d entries)", len(entries))

        # Open once with OVERWRITE to wipe existing index
        db = xapian.WritableDatabase(
            str(self._index_path), xapian.DB_CREATE_OR_OVERWRITE
        )

        count = 0
        for entry in entries:
            self._index_entry_with_db(entry, db)
            count += 1

        # Single commit for all entries
        db.commit()
        db.close()

        logger.info("Rebuild complete: %d entries indexed", count)
        # Rebuild done
        return count

    def get_relations(self, entry_id: str) -> dict[str, list[dict[str, str]]]:
        """
        Get outgoing and incoming graph relations for an entry.

        Outgoing relations are read from the entry's Xapian document terms
        (XRELOUT:{type}:{target_id}). Incoming relations (backlinks) are
        found by searching for documents that have XRELTGT:{entry_id}
        terms, then reading their XRELOUT terms to extract the relation
        type.

        Args:
            entry_id: UUID of the entry.

        Returns:
            Dict with 'out' list (outgoing) and 'in' list (incoming).
            Each item has 'type' and 'id' keys — no title (caller resolves).
        """

        out: list[dict[str, str]] = []
        incoming: list[dict[str, str]] = []

        try:
            db = self._get_readable_db()
        except xapian.DatabaseOpeningError:
            logger.warning("Index not found — returning empty relations")
            # No index
            return {"out": out, "in": incoming}

        # --- Outgoing relations ---
        # Find the document for this entry by its Q-term
        id_term = f"{PREFIX_ID}{entry_id}"
        postlist = db.postlist(id_term)
        try:
            posting = next(postlist)
            doc = db.get_document(posting.docid)

            # Read all XRELOUT: terms from this document
            for term_item in doc:
                term = term_item.term.decode("utf-8")
                if term.startswith(PREFIX_RELOUT):
                    # Parse "XRELOUT:{type}:{target_id}"
                    remainder = term[len(PREFIX_RELOUT) :]
                    colon_pos = remainder.find(":")
                    if colon_pos == -1:
                        continue
                    rel_type = remainder[:colon_pos]
                    target_id = remainder[colon_pos + 1 :]

                    out.append({"type": rel_type, "id": target_id})
        except StopIteration:
            # Entry not in index — no outgoing relations
            pass

        # --- Incoming relations (backlinks) ---
        # Find all documents that have XRELTGT:{entry_id} term
        tgt_term = f"{PREFIX_RELTGT}{entry_id}"
        for posting in db.postlist(tgt_term):
            source_doc = db.get_document(posting.docid)
            source_id = source_doc.get_data().decode("utf-8")

            # Skip self-references
            if source_id == entry_id:
                continue

            # Find the relation type(s) from this source pointing to entry_id
            for term_item in source_doc:
                term = term_item.term.decode("utf-8")
                if not term.startswith(PREFIX_RELOUT):
                    continue
                # Parse "XRELOUT:{type}:{target_id}"
                remainder = term[len(PREFIX_RELOUT) :]
                colon_pos = remainder.find(":")
                if colon_pos == -1:
                    continue
                rel_type = remainder[:colon_pos]
                target_id = remainder[colon_pos + 1 :]

                # Only include if this relation points to our entry
                if target_id != entry_id:
                    continue

                incoming.append({"type": rel_type, "id": source_id})

        # Relations resolved
        return {"out": out, "in": incoming}
