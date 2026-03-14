"""
Knowledge Base — Markdown files + Xapian full-text index.

Manages entries stored as Markdown files with YAML frontmatter. Each entry
has a UUID, title, tags list, and content body. A Xapian index provides
full-text search with French stemming.

Source of truth: the Markdown files. The Xapian index is a rebuildable cache.
"""

from __future__ import annotations

import logging
import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import xapian
import yaml

logger = logging.getLogger("mcp-kb")

# ---------------------------------------------------------------------------
# Xapian prefix constants
# ---------------------------------------------------------------------------

PREFIX_ID: str = "Q"
PREFIX_TITLE: str = "XTITLE"
PREFIX_TAG: str = "XTAG"
PREFIX_RELOUT: str = "XRELOUT:"
PREFIX_RELTGT: str = "XRELTGT:"

# Weighting slots
SLOT_TITLE: int = 0

# Default search limit
DEFAULT_SEARCH_LIMIT: int = 10
DEFAULT_LIST_LIMIT: int = 50

# Duplicate detection threshold (SequenceMatcher ratio, 0.0-1.0)
DUPLICATE_THRESHOLD: float = 0.75

# Regex for extracting kb:// links with optional #type fragment
RE_KB_LINK: re.Pattern[str] = re.compile(
    r"\[[^\]]*\]\(kb://([a-f0-9-]+)(?:#([a-zA-Z0-9_-]+))?\)"
)


class KnowledgeBase:
    """
    Knowledge base backed by Markdown files and a Xapian index.

    Args:
        data_path: Root path for knowledge data (contains entries/ and index/).
    """

    def __init__(self, data_path: str) -> None:
        """
        Initialize the knowledge base.

        Args:
            data_path: Root directory for knowledge storage.

        Errors:
            Creates entries/ and index/ subdirectories if missing.
        """

        self._data_path = Path(data_path)
        self._entries_path = self._data_path / "entries"
        self._index_path = self._data_path / "index" / "fr"

        # Ensure directories exist
        self._entries_path.mkdir(parents=True, exist_ok=True)
        self._index_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            "KnowledgeBase initialized — entries: %s, index: %s",
            self._entries_path,
            self._index_path,
        )

    # -----------------------------------------------------------------------
    # Markdown file operations
    # -----------------------------------------------------------------------

    def _read_entry(self, filepath: Path) -> dict[str, Any] | None:
        """
        Parse a Markdown entry file (YAML frontmatter + body).

        Args:
            filepath: Path to the .md file.

        Returns:
            Dict with id, title, tags, content keys, or None if unparseable.
        """

        try:
            text = filepath.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", filepath, exc)
            # Unreadable file
            return None

        # Split frontmatter (between --- delimiters) from content
        if not text.startswith("---"):
            logger.warning("No frontmatter in %s", filepath)
            # Missing frontmatter
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning("Malformed frontmatter in %s", filepath)
            # Incomplete frontmatter
            return None

        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            logger.warning("YAML parse error in %s: %s", filepath, exc)
            # Bad YAML
            return None

        if not isinstance(meta, dict):
            logger.warning("Frontmatter is not a dict in %s", filepath)
            # Invalid structure
            return None

        content = parts[2].strip()

        # Parsed entry
        return {
            "id": str(meta.get("id", "")),
            "title": str(meta.get("title", "")),
            "tags": _normalize_tags(meta.get("tags", [])),
            "content": content,
        }

    def _write_entry(self, entry: dict[str, Any]) -> Path:
        """
        Write an entry to a Markdown file with YAML frontmatter.

        Args:
            entry: Dict with id, title, tags, content.

        Returns:
            Path to the written file.
        """

        filepath = self._entries_path / f"{entry['id']}.md"

        frontmatter = yaml.dump(
            {"id": entry["id"], "title": entry["title"], "tags": entry["tags"]},
            default_flow_style=True,
            allow_unicode=True,
            sort_keys=False,
        ).strip()

        text = f"---\n{frontmatter}\n---\n\n{entry['content']}\n"
        filepath.write_text(text, encoding="utf-8")

        logger.info("Wrote entry %s to %s", entry["id"], filepath)
        # File written
        return filepath

    def _delete_entry_file(self, entry_id: str) -> bool:
        """
        Delete the Markdown file for an entry.

        Args:
            entry_id: UUID of the entry.

        Returns:
            True if deleted, False if not found.
        """

        filepath = self._entries_path / f"{entry_id}.md"
        if filepath.exists():
            filepath.unlink()
            logger.info("Deleted file %s", filepath)
            # Deleted
            return True

        logger.warning("File not found for deletion: %s", filepath)
        # Not found
        return False

    # -----------------------------------------------------------------------
    # Relation extraction
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_relations(content: str) -> list[dict[str, str]]:
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

    # -----------------------------------------------------------------------
    # Xapian index operations
    # -----------------------------------------------------------------------

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
            Returns None-safe — caller must handle DatabaseOpeningError.
        """

        # Open read-only database
        return xapian.Database(str(self._index_path))

    def _index_entry(self, entry: dict[str, Any]) -> None:
        """
        Index or update an entry in Xapian.

        Uses replace_document with Q<uuid> as the unique ID term for upsert.

        Args:
            entry: Dict with id, title, tags, content.
        """

        db = self._get_writable_db()
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
        relations = self._extract_relations(entry["content"])
        for rel in relations:
            # Outgoing relation term: allows reading this entry's outgoing links
            doc.add_boolean_term(f"{PREFIX_RELOUT}{rel['type']}:{rel['target']}")
            # Target marker term: allows finding all entries that link TO a target
            doc.add_boolean_term(f"{PREFIX_RELTGT}{rel['target']}")

        # Store data for retrieval (title for snippets)
        doc.set_data(entry["id"])

        # Unique ID term for upsert
        id_term = f"{PREFIX_ID}{entry['id']}"
        doc.add_boolean_term(id_term)
        db.replace_document(id_term, doc)

        # Explicit commit to ensure changes are visible to subsequent reads
        db.commit()
        db.close()
        logger.info("Indexed entry %s", entry["id"])

    def _unindex_entry(self, entry_id: str) -> None:
        """
        Remove an entry from the Xapian index.

        Args:
            entry_id: UUID of the entry.
        """

        db = self._get_writable_db()
        id_term = f"{PREFIX_ID}{entry_id}"
        db.delete_document(id_term)
        db.close()
        logger.info("Unindexed entry %s", entry_id)

    def rebuild(self) -> int:
        """
        Rebuild the Xapian index from all Markdown files.

        Deletes the existing index and reindexes every entry file.

        Returns:
            Number of entries indexed.
        """

        logger.info("Rebuilding index from %s", self._entries_path)

        # Delete existing index
        db = xapian.WritableDatabase(
            str(self._index_path), xapian.DB_CREATE_OR_OVERWRITE
        )
        db.close()

        count = 0
        for filepath in sorted(self._entries_path.glob("*.md")):
            entry = self._read_entry(filepath)
            if entry and entry["id"]:
                self._index_entry(entry)
                count += 1
            else:
                logger.warning("Skipped invalid entry: %s", filepath)

        logger.info("Rebuild complete: %d entries indexed", count)
        # Rebuild done
        return count

    # -----------------------------------------------------------------------
    # CRUD operations (file + index)
    # -----------------------------------------------------------------------

    def remember(
        self,
        title: str,
        content: str,
        tags: list[str],
        entry_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Upsert an entry: update if it exists, create if it doesn't.

        Resolution order:
        1. If entry_id is provided → update that entry
        2. If no entry_id → search for similar titles
           - If a match is found above threshold → update the best match
           - If no match → create a new entry
        3. If force=True → always create new (skip duplicate detection)

        Args:
            title: Entry title.
            content: Entry body (Markdown).
            tags: List of tags.
            entry_id: Optional UUID of an existing entry to update.
            force: Skip duplicate detection and always create new.

        Returns:
            Dict with id, title, and action ('created' or 'updated').
        """

        tags = _normalize_tags(tags)

        # Case 1: explicit ID → update
        if entry_id:
            existing = self.get(entry_id)
            if not existing:
                logger.warning("Remember failed — entry %s not found", entry_id)
                # Not found
                return {"error": f"Entry {entry_id} not found"}

            existing["title"] = title
            existing["content"] = content
            existing["tags"] = tags

            self._write_entry(existing)
            self._index_entry(existing)

            logger.info("Updated entry %s: %s", entry_id, title)
            # Updated
            return {"id": entry_id, "title": title, "action": "updated"}

        # Case 2: no ID, check for duplicates (unless forced)
        if not force:
            similar = self.find_similar(title)
            if similar:
                # Update the best match
                best = similar[0]
                best_entry = self.get(best["id"])
                if best_entry:
                    best_entry["title"] = title
                    best_entry["content"] = content
                    best_entry["tags"] = tags

                    self._write_entry(best_entry)
                    self._index_entry(best_entry)

                    logger.info(
                        "Updated existing entry %s (similarity %d%%): %s",
                        best["id"],
                        best["score"],
                        title,
                    )
                    # Updated via duplicate match
                    return {
                        "id": best["id"],
                        "title": title,
                        "action": "updated",
                        "matched": best["title"],
                        "similarity": best["score"],
                    }

        # Case 3: create new
        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "title": title,
            "tags": tags,
            "content": content,
        }

        self._write_entry(entry)
        self._index_entry(entry)

        logger.info("Created new entry %s: %s", entry_id, title)
        # Entry created
        return {"id": entry_id, "title": title, "action": "created"}

    def get(self, entry_id: str, with_relations: bool = False) -> dict[str, Any] | None:
        """
        Read the full content of an entry.

        Args:
            entry_id: UUID of the entry.
            with_relations: Include graph relations (outgoing and incoming links).

        Returns:
            Entry dict or None if not found. When with_relations is True, includes
            a 'relations' key with 'out' and 'in' lists.
        """

        filepath = self._entries_path / f"{entry_id}.md"
        if not filepath.exists():
            # Not found
            return None

        entry = self._read_entry(filepath)
        if not entry:
            # Unparseable
            return None

        # Append graph relations if requested
        if with_relations:
            entry["relations"] = self.get_relations(entry_id)

        # Entry loaded
        return entry

    def get_relations(self, entry_id: str) -> dict[str, list[dict[str, str]]]:
        """
        Get all graph relations for an entry (outgoing and incoming).

        Outgoing relations are read from the entry's Xapian document terms
        (XRELOUT:{type}:{target_id}). Incoming relations (backlinks) are found
        by searching for documents that have XRELTGT:{entry_id} terms, then
        reading their XRELOUT terms to extract the relation type.

        Args:
            entry_id: UUID of the entry.

        Returns:
            Dict with 'out' list (outgoing) and 'in' list (incoming/backlinks).
            Each item has 'type', 'id', and 'title' keys.
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

                    # Resolve target title from file
                    target_title = self._resolve_title(target_id)
                    out.append(
                        {"type": rel_type, "id": target_id, "title": target_title}
                    )
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

                source_title = self._resolve_title(source_id)
                incoming.append(
                    {"type": rel_type, "id": source_id, "title": source_title}
                )

        # Relations resolved
        return {"out": out, "in": incoming}

    def _resolve_title(self, entry_id: str) -> str:
        """
        Read the title of an entry from its Markdown file.

        Args:
            entry_id: UUID of the entry.

        Returns:
            Entry title, or "(unknown)" if the file cannot be read.
        """

        filepath = self._entries_path / f"{entry_id}.md"
        if not filepath.exists():
            # Missing file
            return "(unknown)"

        entry = self._read_entry(filepath)
        if not entry:
            # Unparseable file
            return "(unknown)"

        # Title resolved
        return entry["title"]

    def delete(self, entry_id: str) -> bool:
        """
        Delete an entry (file + index).

        Args:
            entry_id: UUID of the entry.

        Returns:
            True if deleted, False if not found.
        """

        filepath = self._entries_path / f"{entry_id}.md"
        if not filepath.exists():
            logger.warning("Delete failed — entry %s not found", entry_id)
            # Not found
            return False

        self._delete_entry_file(entry_id)

        try:
            self._unindex_entry(entry_id)
        except xapian.DocNotFoundError:
            logger.warning("Entry %s not in index (already removed?)", entry_id)

        logger.info("Deleted entry %s", entry_id)
        # Deleted
        return True

    # -----------------------------------------------------------------------
    # Search operations
    # -----------------------------------------------------------------------

    def search(
        self,
        query_str: str,
        tags: list[str] | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """
        Full-text search with optional tag filtering.

        Args:
            query_str: Search query string.
            tags: Optional list of tags to filter by (AND logic).
            limit: Maximum number of results.

        Returns:
            List of dicts with id, title, tags, snippet, score.
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
            tag_queries = [
                xapian.Query(f"{PREFIX_TAG}{t}") for t in _normalize_tags(tags)
            ]
            tag_query = xapian.Query(xapian.Query.OP_AND, tag_queries)
            query = xapian.Query(xapian.Query.OP_FILTER, query, tag_query)

        enquire = xapian.Enquire(db)
        enquire.set_query(query)

        results = []
        for match in enquire.get_mset(0, limit):
            entry_id = match.document.get_data().decode("utf-8")
            entry = self.get(entry_id)
            if entry:
                # Build snippet (first 200 chars of content)
                snippet = entry["content"][:200]
                if len(entry["content"]) > 200:
                    snippet += "..."

                results.append(
                    {
                        "id": entry["id"],
                        "title": entry["title"],
                        "tags": entry["tags"],
                        "snippet": snippet,
                        "score": match.percent,
                    }
                )

        logger.info("Search '%s' returned %d results", query_str, len(results))
        # Search complete
        return results

    def find_similar(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Find entries with similar titles (for duplicate detection).

        Uses SequenceMatcher on normalized titles for reliable comparison,
        independent of Xapian stemming/scoring quirks.

        Args:
            title: Title to check against existing entries.
            limit: Maximum number of similar entries to return.

        Returns:
            List of dicts with id, title, score for similar entries.
        """

        normalized_title = title.lower().strip()
        similar = []

        for filepath in self._entries_path.glob("*.md"):
            entry = self._read_entry(filepath)
            if not entry or not entry["id"]:
                continue

            ratio = SequenceMatcher(
                None, normalized_title, entry["title"].lower().strip()
            ).ratio()

            if ratio >= DUPLICATE_THRESHOLD:
                similar.append(
                    {
                        "id": entry["id"],
                        "title": entry["title"],
                        "score": int(ratio * 100),
                    }
                )

        # Sort by score descending, limit results
        similar.sort(key=lambda x: -x["score"])

        # Similarity check complete
        return similar[:limit]

    # -----------------------------------------------------------------------
    # Browse operations
    # -----------------------------------------------------------------------

    def list_entries(
        self,
        tags: list[str] | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        """
        List entries sorted by title, with optional tag filter.

        Args:
            tags: Optional list of tags to filter by (AND logic).
            limit: Maximum number of entries.

        Returns:
            List of dicts with id, title, tags.
        """

        filter_tags = set(_normalize_tags(tags)) if tags else None

        entries = []
        for filepath in sorted(self._entries_path.glob("*.md")):
            entry = self._read_entry(filepath)
            if not entry or not entry["id"]:
                continue

            # Apply tag filter
            if filter_tags and not filter_tags.issubset(set(entry["tags"])):
                continue

            entries.append(
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "tags": entry["tags"],
                }
            )

        # Sort by title
        entries.sort(key=lambda e: e["title"].lower())

        # Listed
        return entries[:limit]

    def list_tags(self) -> list[dict[str, Any]]:
        """
        List all tags with their entry counts.

        Returns:
            List of dicts with tag and count, sorted by count descending.
        """

        tag_counts: dict[str, int] = {}

        for filepath in self._entries_path.glob("*.md"):
            entry = self._read_entry(filepath)
            if not entry:
                continue
            for tag in entry["tags"]:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        result = [{"tag": tag, "count": count} for tag, count in tag_counts.items()]
        result.sort(key=lambda x: (-x["count"], x["tag"]))

        # Tags listed
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_tags(tags: Any) -> list[str]:
    """
    Normalize a list of tags: lowercase, strip whitespace, reject empty.

    Args:
        tags: Raw tags input (list or other).

    Returns:
        Cleaned list of tag strings.
    """

    if not isinstance(tags, list):
        # Not a list
        return []

    normalized = []
    for tag in tags:
        clean = str(tag).lower().strip()
        if clean:
            normalized.append(clean)

    # Normalized
    return sorted(set(normalized))
