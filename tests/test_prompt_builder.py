"""Tests for per-turn system prompt building."""

import pytest

from core.prompt_builder import build_system_prompt, build_system_prompt_for_backend
from config import BackendConfig


class TestBuildSystemPrompt:
    """Tests for build_system_prompt()."""

    def test_claude_prompt_includes_balloons_tools(self):
        """Claude backend gets balloons-tool XML documentation."""
        prompt = build_system_prompt(backend_type="claude")

        assert prompt is not None
        assert "<balloons-tool>" in prompt
        assert "propose_fork" in prompt

    def test_openai_prompt_includes_supervisor_docs(self):
        """OpenAI backend gets supervisor tool documentation."""
        prompt = build_system_prompt(backend_type="openai")

        assert prompt is not None
        assert "supervisor" in prompt.lower()
        assert "supervisor_start" in prompt

    def test_user_prompt_included(self):
        """User-provided prompt is included."""
        user_prompt = "You are a helpful assistant."
        prompt = build_system_prompt(backend_type="claude", user_prompt=user_prompt)

        assert prompt is not None
        assert user_prompt in prompt

    def test_user_prompt_first(self):
        """User prompt appears before balloons tools."""
        user_prompt = "CUSTOM_USER_PROMPT_MARKER"
        prompt = build_system_prompt(backend_type="claude", user_prompt=user_prompt)

        user_pos = prompt.find(user_prompt)
        balloons_pos = prompt.find("<balloons-tool>")

        assert user_pos < balloons_pos

    def test_no_user_prompt_still_has_content(self):
        """Even without user prompt, balloons tools are included."""
        prompt = build_system_prompt(backend_type="claude", user_prompt=None)

        assert prompt is not None
        assert len(prompt) > 1000  # Should have balloons tools

    def test_unknown_backend_defaults_to_claude(self):
        """Unknown backend type uses Claude balloons tools."""
        prompt = build_system_prompt(backend_type="unknown")

        # Should get Claude-style prompt (with XML tags)
        assert prompt is not None
        assert "<balloons-tool>" in prompt


class TestBuildSystemPromptForBackend:
    """Tests for build_system_prompt_for_backend()."""

    def test_extracts_user_prompt_from_config(self, tmp_path):
        """User prompt is loaded from backend config file."""
        # Create a temp prompt file
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Backend custom prompt content")

        config = BackendConfig(
            name="test",
            type="claude",
            system_prompt=str(prompt_file),
        )

        prompt = build_system_prompt_for_backend(config)

        assert prompt is not None
        assert "Backend custom prompt content" in prompt

    def test_uses_backend_type(self, tmp_path):
        """Uses correct backend type for prompt selection."""
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Test prompt")

        openai_config = BackendConfig(
            name="test",
            type="openai",
            base_url="http://test",
            system_prompt=str(prompt_file),
        )

        prompt = build_system_prompt_for_backend(openai_config)

        # Should have OpenAI-style docs (supervisor tools, not XML tags)
        assert "supervisor_start" in prompt
        # Should NOT have Claude-style XML tag documentation
        assert "balloons-tool" not in prompt


class TestDomainPromptIntegration:
    """Tests for domain prompt inclusion."""

    def test_domain_prompts_included_when_loaded(self):
        """Domain prompts are included when domains are loaded."""
        from plugins.integration import load_domain, unload_domain

        prompt_before = build_system_prompt(backend_type="claude")

        load_domain("chess", emit_event=False)
        try:
            prompt_with_chess = build_system_prompt(backend_type="claude")

            # Chess domain adds ~2500 chars
            assert len(prompt_with_chess) > len(prompt_before)
            assert "Chess Domain" in prompt_with_chess
        finally:
            unload_domain("chess", emit_event=False)

    def test_domain_prompts_removed_when_unloaded(self):
        """Domain prompts are removed when domains are unloaded."""
        from plugins.integration import load_domain, unload_domain

        prompt_initial = build_system_prompt(backend_type="claude")
        initial_len = len(prompt_initial)

        load_domain("chess", emit_event=False)
        unload_domain("chess", emit_event=False)

        prompt_final = build_system_prompt(backend_type="claude")

        # Should be back to original length
        assert len(prompt_final) == initial_len
