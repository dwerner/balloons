from unittest.mock import MagicMock

from core.runner_factory import create_runner, validate_backend_config
from core.strict_openai_runner import StrictOpenAICompatibleRunner


def test_openai_strict_backend_validates():
    backend = MagicMock(
        type="openai_strict",
        name="mistral-strict",
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="mistral",
        context_window=32000,
    )
    assert validate_backend_config(backend) is None


def test_openai_strict_backend_creates_strict_runner():
    backend = MagicMock(
        type="openai_strict",
        name="mistral-strict",
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="mistral",
        context_window=32000,
    )
    backend.load_system_prompt.return_value = None

    runner = create_runner(backend)
    assert type(runner) is StrictOpenAICompatibleRunner
