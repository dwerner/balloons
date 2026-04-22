"""Tests for per-turn system prompt building."""

import pytest

from core.prompt_builder import build_system_prompt, build_system_prompt_for_backend
from core.tool_prompts import DEFAULT_ENABLED_TOOLS
from config import BackendConfig


class TestBuildSystemPrompt:
    """Tests for build_system_prompt()."""

    def test_prompt_includes_default_tools(self):
        """Prompt includes documentation for default enabled tools."""
        prompt = build_system_prompt(backend_type="openai")

        assert prompt is not None
        # Should have propose_fork (in default enabled tools)
        assert "propose_fork" in prompt
        # Should have domain tools (in default enabled tools)
        assert "load_domain" in prompt

    def test_prompt_includes_enabled_tools_only(self):
        """Prompt only includes enabled tools when specified."""
        # Only enable domain tools
        enabled = {"load_domain", "list_domains"}
        prompt = build_system_prompt(backend_type="openai", enabled_tools=enabled)

        assert prompt is not None
        assert "load_domain" in prompt
        # Should NOT have propose_fork (not in enabled set)
        assert "propose_fork" not in prompt

    def test_user_prompt_included(self):
        """User-provided prompt is included."""
        user_prompt = "You are a helpful assistant."
        prompt = build_system_prompt(backend_type="openai", user_prompt=user_prompt)

        assert prompt is not None
        assert user_prompt in prompt

    def test_user_prompt_first(self):
        """User prompt appears before balloons tools."""
        user_prompt = "CUSTOM_USER_PROMPT_MARKER"
        prompt = build_system_prompt(backend_type="openai", user_prompt=user_prompt)

        user_pos = prompt.find(user_prompt)
        tools_pos = prompt.find("# CRITICAL")  # Start of tool prompts

        assert user_pos < tools_pos

    def test_no_user_prompt_still_has_content(self):
        """Even without user prompt, balloons tools are included."""
        prompt = build_system_prompt(backend_type="openai", user_prompt=None)

        assert prompt is not None
        assert len(prompt) > 1000  # Should have balloons tools

    def test_backend_type_affects_claude_format(self):
        """Claude backend gets extra balloons-tool XML format instructions."""
        prompt_openai = build_system_prompt(backend_type="openai")
        prompt_claude = build_system_prompt(backend_type="claude")
        prompt_unknown = build_system_prompt(backend_type="unknown")

        # OpenAI and unknown backends are the same (no XML format needed)
        assert prompt_openai == prompt_unknown

        # Claude includes balloons-tool XML format instructions
        assert "balloons-tool" in prompt_claude
        assert "balloons-tool" not in prompt_openai


class TestBuildSystemPromptForBackend:
    """Tests for build_system_prompt_for_backend()."""

    def test_extracts_user_prompt_from_config(self, tmp_path):
        """User prompt is loaded from backend config file."""
        # Create a temp prompt file
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Backend custom prompt content")

        config = BackendConfig(
            name="test",
            type="openai",
            base_url="http://test",
            system_prompt=str(prompt_file),
        )

        prompt = build_system_prompt_for_backend(config)

        assert prompt is not None
        assert "Backend custom prompt content" in prompt

    def test_includes_default_tools(self, tmp_path):
        """Includes default tools regardless of backend type."""
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        config = BackendConfig(
            name="test",
            type="openai",
            base_url="http://test",
            system_prompt=str(prompt_file),
        )

        prompt = build_system_prompt_for_backend(config)

        # Should have default tools
        assert "propose_fork" in prompt
        assert "load_domain" in prompt


class TestDomainPromptIntegration:
    """Tests for domain prompt inclusion."""

    def test_domain_prompts_included_when_loaded(self):
        """Domain prompts are included when domains are loaded."""
        from plugins.integration import load_domain, unload_domain

        prompt_before = build_system_prompt(backend_type="openai")

        load_domain("chess", emit_event=False)
        try:
            prompt_with_chess = build_system_prompt(backend_type="openai")

            # Chess domain adds ~2500 chars
            assert len(prompt_with_chess) > len(prompt_before)
            assert "Chess Domain" in prompt_with_chess
        finally:
            unload_domain("chess", emit_event=False)

    def test_domain_prompts_removed_when_unloaded(self):
        """Domain prompts are removed when domains are unloaded."""
        from plugins.integration import load_domain, unload_domain

        prompt_initial = build_system_prompt(backend_type="openai")
        initial_len = len(prompt_initial)

        load_domain("chess", emit_event=False)
        unload_domain("chess", emit_event=False)

        prompt_final = build_system_prompt(backend_type="openai")

        # Should be back to original length
        assert len(prompt_final) == initial_len
