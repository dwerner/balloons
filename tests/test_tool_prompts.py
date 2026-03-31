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
        # Enable just domain tools
        enabled = {"load_domain", "unload_domain", "list_domains"}
        prompt = build_tool_prompts(enabled)

        assert "load_domain" in prompt
        assert "unload_domain" in prompt
        assert "list_domains" in prompt
        # Should NOT have balloon tools
        assert "ask_user" not in prompt
        assert "propose_fork" not in prompt

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
