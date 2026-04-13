import pytest
import openai

from src.utils.exceptions import LLMUnavailableError


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("ROUTERAI_BASE_URL", "https://fake.routerai.ru/v1")
    monkeypatch.setenv("ROUTERAI_API_KEY", "fake_key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_TIMEOUT", "5")


def _make_completion(content: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    """Build a minimal fake openai ChatCompletion response."""
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


class TestLLMClient:
    def test_successful_call(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from src.agent.llm_client import LLMClient

        fake_resp = _make_completion("ACTION: finalize\nDIALOGUE: {}")

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = fake_resp

            client = LLMClient()
            result = client.call([{"role": "user", "content": "test"}])

        assert result.content == "ACTION: finalize\nDIALOGUE: {}"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20

    def test_retries_on_timeout_then_succeeds(self, monkeypatch):
        from unittest.mock import MagicMock, call, patch
        from src.agent.llm_client import LLMClient

        fake_resp = _make_completion("ok")
        call_count = {"n": 0}

        def side_effect(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise openai.APITimeoutError(request=MagicMock())
            return fake_resp

        monkeypatch.setattr("time.sleep", lambda s: None)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = side_effect

            client = LLMClient()
            result = client.call([{"role": "user", "content": "x"}])

        assert result.content == "ok"
        assert call_count["n"] == 3

    def test_raises_after_3_timeouts(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from src.agent.llm_client import LLMClient

        monkeypatch.setattr("time.sleep", lambda s: None)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.APITimeoutError(
                request=MagicMock()
            )

            client = LLMClient()
            with pytest.raises(LLMUnavailableError):
                client.call([{"role": "user", "content": "x"}])

    def test_raises_immediately_on_auth_error(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        from src.agent.llm_client import LLMClient

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
                message="Invalid key", response=MagicMock(), body={}
            )

            client = LLMClient()
            with pytest.raises(LLMUnavailableError, match="auth failed"):
                client.call([{"role": "user", "content": "x"}])
