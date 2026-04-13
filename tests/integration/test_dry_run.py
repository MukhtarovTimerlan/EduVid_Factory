"""
Integration dry-run test.
Mocks LLMClient and SearchTool; exercises the full pipeline without TTS/video.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from src.agent.llm_client import LLMResponse


@pytest.fixture(autouse=True)
def set_required_env(monkeypatch):
    monkeypatch.setenv("ROUTERAI_BASE_URL", "https://fake.routerai.ru/v1")
    monkeypatch.setenv("ROUTERAI_API_KEY", "fake_key")
    monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
    monkeypatch.setenv("AGENT_MAX_STEPS", "3")


def _finalize_response(topic: str = "photosynthesis") -> LLMResponse:
    dialogue = {
        "lines": [
            {"speaker": "A", "text": f"Today we explore {topic}."},
            {"speaker": "B", "text": f"What is {topic} exactly?"},
            {"speaker": "A", "text": f"{topic} is the process by which plants make energy."},
            {"speaker": "B", "text": "That is fascinating, thank you!"},
        ]
    }
    return LLMResponse(
        content=f"ACTION: finalize\nDIALOGUE: {json.dumps(dialogue)}",
        prompt_tokens=200,
        completion_tokens=150,
    )


class TestDryRun:
    def test_dry_run_returns_without_error(self, tmp_path):
        """Full pipeline dry-run: agent runs, dialogue produced, no TTS/video."""
        from src.pipeline_orchestrator import PipelineOrchestrator

        with patch("src.agent.llm_client.openai.OpenAI") as mock_openai:
            mock_oai_client = MagicMock()
            mock_openai.return_value = mock_oai_client
            mock_oai_client.chat.completions.create.return_value = _build_oai_response(
                _finalize_response().content
            )

            with patch("src.tools.search.DDGS", _FakeDDGS):
                orchestrator = PipelineOrchestrator(
                    output_dir=str(tmp_path / "output"),
                    dry_run=True,
                    log_level="WARNING",
                )
                result = orchestrator.run(topic="photosynthesis", style_hint="for beginners")

        assert result is not None

    def test_dry_run_with_search_step(self, tmp_path):
        """Dry-run where agent does one search before finalizing."""
        from src.pipeline_orchestrator import PipelineOrchestrator

        search_then_finalize = [
            LLMResponse(
                content="ACTION: search\nQUERY: photosynthesis explained",
                prompt_tokens=100,
                completion_tokens=20,
            ),
            _finalize_response(),
        ]

        call_count = {"n": 0}

        def fake_create(**kw):
            resp = search_then_finalize[call_count["n"]]
            call_count["n"] += 1
            return _build_oai_response(resp.content, resp.prompt_tokens, resp.completion_tokens)

        with patch("src.agent.llm_client.openai.OpenAI") as mock_openai:
            mock_oai_client = MagicMock()
            mock_openai.return_value = mock_oai_client
            mock_oai_client.chat.completions.create.side_effect = fake_create

            with patch("src.tools.search.DDGS", _FakeDDGS):
                orchestrator = PipelineOrchestrator(
                    output_dir=str(tmp_path / "output"),
                    dry_run=True,
                    log_level="WARNING",
                )
                result = orchestrator.run(topic="photosynthesis")

        assert result is not None
        assert call_count["n"] == 2  # search + finalize

    def test_configuration_error_on_missing_env(self, monkeypatch):
        """PipelineOrchestrator raises ConfigurationError if env vars missing."""
        from src.pipeline_orchestrator import PipelineOrchestrator
        from src.utils.exceptions import ConfigurationError

        monkeypatch.delenv("ROUTERAI_API_KEY", raising=False)

        with pytest.raises(ConfigurationError, match="ROUTERAI_API_KEY"):
            PipelineOrchestrator(dry_run=True)


# ── helpers ───────────────────────────────────────────────────────────────────

class _FakeDDGS:
    """DuckDuckGo stub that returns one canned result."""
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def text(self, *_args, **_kw):
        return [{"title": "Photosynthesis", "body": "The process by which plants use sunlight.", "href": "https://example.com"}]


def _build_oai_response(content: str, prompt_tokens: int = 200, completion_tokens: int = 150):
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp
