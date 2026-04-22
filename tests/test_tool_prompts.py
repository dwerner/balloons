"""Tests for per-tool prompt building system."""

import pytest
from pathlib import Path

from core.tool_prompts import (
    build_tool_prompts,
    TOOL_CATEGORIES,
    ALL_BALLOON_TOOLS,
    DEFAULT_ENABLED_TOOLS,
    CORE_TOOLS,
    get_tools_in_category,
    get_all_categories,
    get_category_for_tool,
    discover_tool_categories,
    clear_discovery_cache,
    get_all_balloon_tools,
    get_all_tools,
)


class TestToolCategories:
    """Tests for tool category structure."""

    def test_all_categories_have_prompt_files(self):
        """Each tool in TOOL_CATEGORIES should have a corresponding prompt file."""
        prompts_dir = Path(__file__).parent.parent / "prompts" / "tools"

        missing = []
        for category, tools in TOOL_CATEGORIES.items():
            category_dir = prompts_dir / category
            for tool_name in tools:
                tool_file = category_dir / f"{tool_name}.md"
                if not tool_file.exists():
                    missing.append(f"{category}/{tool_name}.md")

        assert not missing, f"Missing prompt files: {missing}"

    def test_all_balloon_tools_computed_correctly(self):
        """ALL_BALLOON_TOOLS should contain all tools from all categories."""
        expected = set()
        for tools in TOOL_CATEGORIES.values():
            expected.update(tools)

        assert ALL_BALLOON_TOOLS == expected

    def test_default_enabled_includes_core_tools(self):
        """Default enabled tools should include all core tools."""
        for tool in CORE_TOOLS:
            assert tool in DEFAULT_ENABLED_TOOLS, f"Core tool {tool} not in defaults"

    def test_category_helper_functions(self):
        """Test get_tools_in_category, get_all_categories, get_category_for_tool."""
        # get_all_categories
        categories = get_all_categories()
        assert "balloon" in categories
        assert "domain" in categories

        # get_tools_in_category
        balloon_tools = get_tools_in_category("balloon")
        assert "ask_user" in balloon_tools
        assert "propose_fork" in balloon_tools

        # get_category_for_tool
        assert get_category_for_tool("ask_user") == "balloon"
        assert get_category_for_tool("load_domain") == "domain"
        assert get_category_for_tool("nonexistent") is None


class TestBuildToolPrompts:
    """Tests for build_tool_prompts()."""

    def test_includes_critical_usage_by_default(self):
        """Prompt should include critical usage template by default."""
        prompt = build_tool_prompts(DEFAULT_ENABLED_TOOLS)

        assert "CRITICAL" in prompt
        assert "call tools" in prompt.lower()

    def test_can_disable_critical_usage(self):
        """Can build without critical usage template."""
        prompt = build_tool_prompts(DEFAULT_ENABLED_TOOLS, include_critical_usage=False)

        # Should still have tool docs but maybe not the critical section
        assert "ask_user" in prompt or "load_domain" in prompt

    def test_includes_only_enabled_tools(self):
        """Only enabled tools should have documentation in the prompt."""
        # Enable just domain tools (as a list)
        enabled = ["load_domain", "unload_domain", "list_domains"]
        prompt = build_tool_prompts(enabled)

        assert "load_domain" in prompt
        assert "unload_domain" in prompt
        assert "list_domains" in prompt
        # Should NOT have balloon tools
        assert "ask_user" not in prompt
        assert "propose_fork" not in prompt

    def test_order_preserved_from_list(self):
        """Order of tools in the list determines prompt order."""
        # Put domain tools first, then balloon tools
        enabled = ["load_domain", "list_domains", "ask_user", "propose_fork"]
        prompt = build_tool_prompts(enabled)

        # Domain tools should appear before balloon tools
        load_domain_pos = prompt.find("load_domain")
        ask_user_pos = prompt.find("ask_user")
        assert load_domain_pos < ask_user_pos, "Domain tools should come before balloon tools"

        # Now reverse the order
        enabled_reversed = ["ask_user", "propose_fork", "load_domain", "list_domains"]
        prompt_reversed = build_tool_prompts(enabled_reversed)

        # Balloon tools should appear before domain tools
        load_domain_pos = prompt_reversed.find("load_domain")
        ask_user_pos = prompt_reversed.find("ask_user")
        assert ask_user_pos < load_domain_pos, "Balloon tools should come before domain tools"

    def test_empty_enabled_still_has_critical(self):
        """Even with no tools enabled, should have critical usage."""
        prompt = build_tool_prompts(set())

        assert "CRITICAL" in prompt

    def test_category_overview_included(self):
        """Category overview should be included when tools from that category are enabled."""
        # Enable domain tools which have an _overview.md
        enabled = {"load_domain", "list_domains"}
        prompt = build_tool_prompts(enabled)

        # Should include the overview content
        assert "Domain Plugin" in prompt

    def test_all_default_tools_have_docs(self):
        """All default enabled tools should have documentation."""
        prompt = build_tool_prompts(DEFAULT_ENABLED_TOOLS)

        # Check a few key tools from different categories
        # Balloon tools
        assert "ask_user" in prompt
        assert "propose_fork" in prompt
        # Domain tools
        assert "load_domain" in prompt


class TestPromptFileStructure:
    """Tests for prompt file structure."""

    def test_template_files_exist(self):
        """Critical templates should exist."""
        templates_dir = Path(__file__).parent.parent / "prompts" / "tools" / "_templates"

        assert (templates_dir / "tool_usage_critical.md").exists()

    def test_each_category_has_directory(self):
        """Each category in TOOL_CATEGORIES should have a directory."""
        prompts_dir = Path(__file__).parent.parent / "prompts" / "tools"

        for category in TOOL_CATEGORIES:
            category_dir = prompts_dir / category
            assert category_dir.exists(), f"Missing directory for category: {category}"
            assert category_dir.is_dir(), f"Not a directory: {category}"


class TestDefaultEnabledTools:
    """Tests for default enabled tools configuration."""

    def test_domain_tools_in_defaults(self):
        """Domain management tools should be in defaults."""
        assert "load_domain" in DEFAULT_ENABLED_TOOLS
        assert "unload_domain" in DEFAULT_ENABLED_TOOLS
        assert "list_domains" in DEFAULT_ENABLED_TOOLS

    def test_core_workflow_tools_in_defaults(self):
        """Core workflow tools should be in defaults."""
        assert "ask_user" in DEFAULT_ENABLED_TOOLS
        assert "propose_fork" in DEFAULT_ENABLED_TOOLS
        assert "propose_merge" in DEFAULT_ENABLED_TOOLS

    def test_session_navigation_in_defaults(self):
        """Session navigation tools should be in defaults."""
        assert "session_info" in DEFAULT_ENABLED_TOOLS
        assert "list_links" in DEFAULT_ENABLED_TOOLS
        assert "follow_link" in DEFAULT_ENABLED_TOOLS

    def test_supervisor_tools_not_in_defaults(self):
        """Supervisor tools should NOT be in defaults (they're optional)."""
        assert "supervisor_start" not in DEFAULT_ENABLED_TOOLS
        assert "supervisor_stop" not in DEFAULT_ENABLED_TOOLS

    def test_debug_tools_not_in_defaults(self):
        """Debug tools should NOT be in defaults (they're for debugging)."""
        assert "debug_log_query" not in DEFAULT_ENABLED_TOOLS


class TestFilesystemDiscovery:
    """Tests for filesystem-based tool discovery."""

    def test_discover_tool_categories_returns_dict(self):
        """discover_tool_categories() should return a dict of categories."""
        categories = discover_tool_categories()
        assert isinstance(categories, dict)
        assert len(categories) > 0

    def test_discovered_categories_match_directories(self):
        """Discovered categories should match directories in prompts/tools/."""
        prompts_dir = Path(__file__).parent.parent / "prompts" / "tools"
        categories = discover_tool_categories()

        # Check that expected categories are discovered
        expected = ["balloon", "browser", "debug", "domain", "midi", "supervisor", "watcher"]
        for cat in expected:
            assert cat in categories, f"Category {cat} should be discovered"

        # Check that excluded directories are NOT discovered
        assert "_templates" not in categories
        assert "openai" not in categories

    def test_discovered_tools_match_md_files(self):
        """Discovered tools should match .md files in category directories."""
        prompts_dir = Path(__file__).parent.parent / "prompts" / "tools"
        categories = discover_tool_categories()

        for category, tools in categories.items():
            category_dir = prompts_dir / category
            if category_dir.exists():
                # Check that each tool has a corresponding .md file
                for tool in tools:
                    tool_file = category_dir / f"{tool}.md"
                    assert tool_file.exists(), f"Tool {tool} should have {tool_file}"

    def test_discovered_excludes_overview_files(self):
        """_overview.md files should not be included as tools."""
        categories = discover_tool_categories()

        for category, tools in categories.items():
            assert "_overview" not in tools, f"_overview should not be a tool in {category}"

    def test_legacy_aliases_match_discovery(self):
        """Legacy TOOL_CATEGORIES and ALL_BALLOON_TOOLS should match discovery."""
        discovered = discover_tool_categories()

        # TOOL_CATEGORIES should equal discovered
        assert TOOL_CATEGORIES == discovered

        # ALL_BALLOON_TOOLS should equal union of all discovered tools
        expected_all = set()
        for tools in discovered.values():
            expected_all.update(tools)
        assert ALL_BALLOON_TOOLS == expected_all

    def test_get_all_balloon_tools_function(self):
        """get_all_balloon_tools() should return all discovered balloon tools."""
        all_tools = get_all_balloon_tools()
        assert isinstance(all_tools, set)
        assert "ask_user" in all_tools
        assert "browser_start" in all_tools
        assert "load_domain" in all_tools

    def test_get_all_tools_includes_core(self):
        """get_all_tools() should include core tools plus balloon tools."""
        all_tools = get_all_tools()
        # Should include core tools
        for core in CORE_TOOLS:
            assert core in all_tools, f"Core tool {core} should be in all tools"
        # Should include balloon tools
        assert "ask_user" in all_tools

    def test_cache_clearing(self):
        """clear_discovery_cache() should allow re-discovery."""
        # First discovery
        cats1 = discover_tool_categories()

        # Clear and re-discover
        clear_discovery_cache()
        cats2 = discover_tool_categories()

        # Should be the same (filesystem unchanged)
        assert cats1 == cats2
