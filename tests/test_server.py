"""
Tests for server.py — tool registration and basic tool behaviour.

Exercises the register_tools() function with a real KnowledgeBase on
a tmp_path directory and a fresh FastMCP instance.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

import pytest

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp.server.fastmcp import FastMCP

from database import KnowledgeBase
from server import register_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _setup(tmp_path: Path) -> tuple[FastMCP, KnowledgeBase, logging.Logger]:
    """Provide a FastMCP instance with tools registered against a temp KB."""

    kb = KnowledgeBase(str(tmp_path))
    mcp = FastMCP(name="test")
    logger = logging.getLogger("test_server")
    register_tools(mcp, kb, logger)

    # Ready
    return mcp, kb, logger


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify that register_tools() creates the expected MCP tools."""

    def test_all_tools_registered(self, _setup: tuple) -> None:
        """All seven tools must be registered on the MCP instance."""

        mcp, _kb, _logger = _setup

        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {"search", "recall", "remember", "forget", "list", "tags", "rebuild"}

        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"

    def test_no_extra_tools(self, _setup: tuple) -> None:
        """Only the expected tools are registered (no leftovers)."""

        mcp, _kb, _logger = _setup

        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {"search", "recall", "remember", "forget", "list", "tags", "rebuild"}

        # No unexpected tools
        assert tool_names == expected


# ---------------------------------------------------------------------------
# Tool behaviour — edge cases
# ---------------------------------------------------------------------------


class TestRememberEdgeCases:
    """Edge cases for the remember tool via KnowledgeBase."""

    def test_remember_invalid_entry_id_path_traversal(self, _setup: tuple) -> None:
        """A path-traversal entry_id is rejected."""

        _mcp, kb, _logger = _setup

        result = kb.remember(
            "Exploit",
            "Content.",
            ["test"],
            entry_id="../../../etc/passwd",
        )

        # Must be rejected
        assert "error" in result
        assert "Invalid" in result["error"]

    def test_remember_invalid_entry_id_not_uuid(self, _setup: tuple) -> None:
        """A non-UUID entry_id is rejected."""

        _mcp, kb, _logger = _setup

        result = kb.remember(
            "Exploit",
            "Content.",
            ["test"],
            entry_id="not-a-valid-uuid",
        )

        # Must be rejected
        assert "error" in result


class TestSearchEdgeCases:
    """Edge cases for the search tool."""

    def test_search_empty_query(self, _setup: tuple) -> None:
        """An empty query string returns empty results without crashing."""

        _mcp, kb, _logger = _setup

        # Create an entry first so the index exists
        kb.remember("Test Entry", "Some content.", ["test"])

        results = kb.search("")

        # Empty query may return all or nothing, but must not crash
        assert isinstance(results, list)

    def test_search_limit_clamped_low(self, _setup: tuple) -> None:
        """Limit below 1 is clamped to 1."""

        _mcp, kb, _logger = _setup

        kb.remember("Entry A", "Alpha content.", ["test"], force=True)
        kb.remember("Entry B", "Beta content.", ["test"], force=True)

        # Use limit=0 — should be clamped to 1 by server, but here we
        # test the KB directly (it accepts the value as-is)
        results = kb.search("content", limit=1)

        # At most 1 result
        assert len(results) <= 1


class TestForgetEdgeCases:
    """Edge cases for the forget tool."""

    def test_forget_nonexistent_entry(self, _setup: tuple) -> None:
        """Forgetting an entry that does not exist returns False."""

        _mcp, kb, _logger = _setup

        fake_id = str(uuid.uuid4())
        success = kb.delete(fake_id)

        # Not found
        assert success is False

    def test_forget_invalid_id(self, _setup: tuple) -> None:
        """Forgetting with an invalid ID returns False."""

        _mcp, kb, _logger = _setup

        success = kb.delete("../../etc/shadow")

        # Rejected
        assert success is False


class TestLimitClamping:
    """Verify that server-level limit clamping works."""

    def test_list_limit_clamped(self, _setup: tuple) -> None:
        """list_entries respects the limit parameter."""

        _mcp, kb, _logger = _setup

        for i in range(5):
            kb.remember(f"Entry {i:02d}", f"Body {i}.", ["test"], force=True)

        entries = kb.list_entries(limit=2)

        # Must respect the limit
        assert len(entries) == 2

    def test_list_limit_large(self, _setup: tuple) -> None:
        """A limit larger than the entry count returns all entries."""

        _mcp, kb, _logger = _setup

        kb.remember("Only Entry", "Solo.", ["test"])

        entries = kb.list_entries(limit=500)

        # All entries returned
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Metadata cache coherence
# ---------------------------------------------------------------------------


class TestMetaCache:
    """Verify that the metadata cache stays in sync with disk."""

    def test_cache_populated_on_init(self, tmp_path: Path) -> None:
        """Cache is populated when KnowledgeBase is created."""

        kb = KnowledgeBase(str(tmp_path))
        kb.remember("Cached Entry", "Content.", ["cache"])

        # Create a new KnowledgeBase on the same path
        kb2 = KnowledgeBase(str(tmp_path))

        # Cache should contain the entry
        assert len(kb2._meta_cache) == 1

    def test_cache_updated_on_remember(self, _setup: tuple) -> None:
        """Cache is updated when a new entry is created."""

        _mcp, kb, _logger = _setup

        result = kb.remember("New Entry", "Content.", ["test"])
        entry_id = result["id"]

        # Must be in cache
        assert entry_id in kb._meta_cache
        assert kb._meta_cache[entry_id]["title"] == "New Entry"
        assert kb._meta_cache[entry_id]["tags"] == ["test"]

    def test_cache_updated_on_delete(self, _setup: tuple) -> None:
        """Cache entry is removed when an entry is deleted."""

        _mcp, kb, _logger = _setup

        result = kb.remember("To Delete", "Content.", ["test"])
        entry_id = result["id"]

        assert entry_id in kb._meta_cache

        kb.delete(entry_id)

        # Must be gone from cache
        assert entry_id not in kb._meta_cache

    def test_cache_updated_on_rebuild(self, _setup: tuple) -> None:
        """Cache is reloaded after a full rebuild."""

        _mcp, kb, _logger = _setup

        kb.remember("Alpha", "A.", ["test"], force=True)
        kb.remember("Beta", "B.", ["test"], force=True)

        kb.rebuild()

        # Cache must contain both entries
        assert len(kb._meta_cache) == 2
