"""Tests for the domain registry."""

import pytest
from pathlib import Path

from .registry import DomainRegistry
from .base import Domain, ToolDef, ToolResult


class TestDomainRegistry:
    def test_load_chess_domain(self):
        """Test loading the chess domain."""
        registry = DomainRegistry(Path(__file__).parent)
        domain = registry.load_domain("chess")

        assert domain.id == "chess"
        assert domain.name == "Chess"
        assert "chess" in registry.loaded_domains

    def test_get_chess_tools(self):
        """Test getting tools from chess domain."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        tools = registry.get_all_tools()
        tool_names = {t["function"]["name"] for t in tools}

        assert "chess_new_game" in tool_names
        assert "chess_move" in tool_names
        assert "chess_show" in tool_names
        assert "chess_legal_moves" in tool_names

    def test_is_domain_tool(self):
        """Test checking if a tool belongs to a domain."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        assert registry.is_domain_tool("chess_new_game")
        assert registry.is_domain_tool("chess_move")
        assert not registry.is_domain_tool("unknown_tool")

    def test_get_all_prompts(self):
        """Test getting prompts from all domains."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        prompts = registry.get_all_prompts()
        assert "Chess" in prompts
        assert "chess_move" in prompts

    def test_unload_domain(self):
        """Test unloading a domain."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        assert "chess" in registry.loaded_domains

        registry.unload_domain("chess")
        assert "chess" not in registry.loaded_domains
        assert not registry.is_domain_tool("chess_move")

    def test_reload_domain(self):
        """Test reloading a domain."""
        registry = DomainRegistry(Path(__file__).parent)
        domain1 = registry.load_domain("chess")

        # Reload
        domain2 = registry.reload_domain("chess")

        # Should be different instances
        assert domain1 is not domain2
        assert domain2.id == "chess"

    def test_duplicate_load_fails(self):
        """Test that loading a domain twice fails."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        with pytest.raises(ValueError, match="already loaded"):
            registry.load_domain("chess")

    def test_unload_not_loaded_fails(self):
        """Test that unloading a non-loaded domain fails."""
        registry = DomainRegistry(Path(__file__).parent)

        with pytest.raises(ValueError, match="not loaded"):
            registry.unload_domain("chess")


@pytest.mark.asyncio
class TestChessDomainExecution:
    """Test actual chess domain tool execution."""

    async def test_new_game(self):
        """Test starting a new chess game."""
        from .chess import ChessDomain

        # Create a mock session
        class MockSession:
            id = "test-session"

        domain = ChessDomain()
        result = await domain.handle_tool("chess_new_game", {}, MockSession())

        assert not result.is_error
        assert "New chess game started" in result.result
        assert any(e.type == "chess_game_started" for e in result.events)

    async def test_make_move(self):
        """Test making a chess move."""
        from .chess import ChessDomain

        class MockSession:
            id = "test-session-2"

        domain = ChessDomain()

        # Start a game first
        await domain.handle_tool("chess_new_game", {}, MockSession())

        # Make a move
        result = await domain.handle_tool("chess_move", {"move": "e2e4"}, MockSession())

        assert not result.is_error
        assert "e2e4" in result.result
        assert any(e.type == "chess_move_made" for e in result.events)

    async def test_illegal_move(self):
        """Test that illegal moves are rejected."""
        from .chess import ChessDomain

        class MockSession:
            id = "test-session-3"

        domain = ChessDomain()

        # Start a game first
        await domain.handle_tool("chess_new_game", {}, MockSession())

        # Try an illegal move
        result = await domain.handle_tool("chess_move", {"move": "e2e5"}, MockSession())

        assert result.is_error
        assert "Illegal move" in result.result or "Invalid" in result.result


@pytest.mark.asyncio
class TestProviderProtocol:
    """Test that the registry implements the provider protocols."""

    def test_registry_has_provider_methods(self):
        """Test that registry implements ToolProvider/PromptProvider."""
        registry = DomainRegistry(Path(__file__).parent)

        # Check ToolProvider methods
        assert hasattr(registry, "get_tools")
        assert hasattr(registry, "get_tool_names")
        assert hasattr(registry, "handles_tool")
        assert hasattr(registry, "execute_tool_as_provider")

        # Check PromptProvider methods
        assert hasattr(registry, "get_prompt")

        # Check state methods
        assert hasattr(registry, "get_state")

    def test_handles_tool(self):
        """Test handles_tool method."""
        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        assert registry.handles_tool("chess_new_game")
        assert registry.handles_tool("chess_move")
        assert not registry.handles_tool("unknown_tool")

    async def test_execute_tool_as_provider(self):
        """Test execute_tool_as_provider method."""
        class MockSession:
            id = "test-provider-session"

        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        # Test executing a tool
        result, is_error = await registry.execute_tool_as_provider(
            "chess_new_game",
            {},
            MockSession(),
            "/tmp",
        )

        assert not is_error
        assert "New chess game started" in result

    async def test_execute_unknown_tool_as_provider(self):
        """Test that unknown tools return error."""
        class MockSession:
            id = "test-provider-session-2"

        registry = DomainRegistry(Path(__file__).parent)

        result, is_error = await registry.execute_tool_as_provider(
            "unknown_tool",
            {},
            MockSession(),
            "/tmp",
        )

        assert is_error
        assert "Unknown" in result

    async def test_get_state(self):
        """Test getting state from a stateful domain."""
        class MockSession:
            id = "test-state-session"

        registry = DomainRegistry(Path(__file__).parent)
        registry.load_domain("chess")

        # No state before starting a game
        state = await registry.get_state("chess", MockSession())
        assert state is None

        # Start a game
        await registry.execute_tool("chess_new_game", {}, MockSession())

        # Now we should have state
        state = await registry.get_state("chess", MockSession())
        assert state is not None
        assert "fen" in state
        assert "legal_moves" in state
        assert state["game_over"] is False

    async def test_get_state_unknown_domain(self):
        """Test that get_state returns None for unknown domains."""
        class MockSession:
            id = "test-state-session-2"

        registry = DomainRegistry(Path(__file__).parent)

        state = await registry.get_state("unknown_domain", MockSession())
        assert state is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
