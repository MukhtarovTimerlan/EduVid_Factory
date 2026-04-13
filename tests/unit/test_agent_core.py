"""
Unit tests for AgentCore state machine.
All external dependencies (LLMClient, SearchTool) are mocked.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from src.agent.agent_core import AgentCore
from src.agent.llm_client import LLMResponse
from src.agent.memory import SessionMemory
from src.utils.cost_tracker import CostTracker
from src.utils.exceptions import BudgetExceededError, LLMUnavailableError
from src.utils.validators import DialogueModel, DialogueValidator


# ── Helpers ────────────────────────────────────────────────────────────────────

def _valid_dialogue_json(topic: str = "test") -> str:
    return json.dumps({
        "lines": [
            {"speaker": "A", "text": f"Let's talk about {topic}."},
            {"speaker": "B", "text": f"Great, tell me more about {topic}."},
            {"speaker": "A", "text": f"{topic} is very important."},
            {"speaker": "B", "text": "I understand, thanks!"},
        ]
    })


def _llm_search_response(query: str = "test query") -> LLMResponse:
    return LLMResponse(
        content=f"ACTION: search\nQUERY: {query}",
        prompt_tokens=100,
        completion_tokens=20,
    )


def _llm_finalize_response(topic: str = "test") -> LLMResponse:
    return LLMResponse(
        content=f"ACTION: finalize\nDIALOGUE: {_valid_dialogue_json(topic)}",
        prompt_tokens=200,
        completion_tokens=150,
    )


def _make_agent(llm_responses: list, search_result: list | None = None) -> AgentCore:
    llm_mock = MagicMock()
    llm_mock.call.side_effect = llm_responses

    search_mock = MagicMock()
    search_mock.query.return_value = search_result or ["Title: X | Snippet: Y"]

    return AgentCore(
        llm_client=llm_mock,
        search_tool=search_mock,
        memory=SessionMemory(),
        cost_tracker=CostTracker(),
        validator=DialogueValidator(),
        logger=None,
    )


@pytest.fixture(autouse=True)
def set_cost_env(monkeypatch):
    monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
    monkeypatch.setenv("AGENT_MAX_STEPS", "3")


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_single_search_then_finalize(self):
        agent = _make_agent([
            _llm_search_response("gradient boosting"),
            _llm_finalize_response("gradient boosting"),
        ])
        result = agent.run_react_loop("gradient boosting")
        assert isinstance(result, DialogueModel)
        assert len(result.lines) == 4

    def test_direct_finalize_no_search(self):
        agent = _make_agent([_llm_finalize_response("photosynthesis")])
        result = agent.run_react_loop("photosynthesis")
        assert isinstance(result, DialogueModel)

    def test_memory_is_cleared_after_loop(self):
        memory = SessionMemory()
        llm_mock = MagicMock()
        llm_mock.call.return_value = _llm_finalize_response()
        agent = AgentCore(
            llm_client=llm_mock,
            search_tool=MagicMock(),
            memory=memory,
            cost_tracker=CostTracker(),
            validator=DialogueValidator(),
        )
        agent.run_react_loop("topic")
        assert memory.get_history() == []


class TestParseErrorRetry:
    def test_correction_hint_injected_on_parse_error(self):
        bad_response = LLMResponse(content="I don't know what to do.", prompt_tokens=10, completion_tokens=10)
        agent = _make_agent([
            bad_response,
            bad_response,
            _llm_finalize_response(),  # succeeds on 3rd attempt
        ])
        result = agent.run_react_loop("test")
        assert isinstance(result, DialogueModel)

    def test_fallback_dialogue_after_parse_retries_exhausted(self):
        bad_response = LLMResponse(content="garbage output", prompt_tokens=10, completion_tokens=10)
        # All 5 calls return garbage (initial + 2 parse retries + force_finalize + fallback path)
        agent = _make_agent([bad_response] * 10)
        result = agent.run_react_loop("test topic")
        # Should return fallback dialogue with topic substituted
        assert isinstance(result, DialogueModel)
        assert len(result.lines) >= 2
        assert any("test topic" in line.text for line in result.lines)


class TestValidationErrorRetry:
    def test_schema_example_injected_on_validation_error(self):
        bad_json = LLMResponse(
            content='ACTION: finalize\nDIALOGUE: {"lines": [{"speaker": "A", "text": "x"}]}',  # 1 line < 2
            prompt_tokens=50,
            completion_tokens=30,
        )
        agent = _make_agent([
            bad_json,
            _llm_finalize_response(),  # succeeds on retry
        ])
        result = agent.run_react_loop("quantum computing")
        assert isinstance(result, DialogueModel)
        assert len(result.lines) >= 2

    def test_fallback_dialogue_after_val_retries_exhausted(self):
        bad_json = LLMResponse(
            content='ACTION: finalize\nDIALOGUE: {"lines": []}',  # 0 lines
            prompt_tokens=50,
            completion_tokens=30,
        )
        agent = _make_agent([bad_json] * 10)
        result = agent.run_react_loop("blockchain")
        assert isinstance(result, DialogueModel)
        assert any("blockchain" in line.text for line in result.lines)


class TestIterationLimit:
    def test_force_finalize_after_max_steps(self):
        agent = _make_agent([
            _llm_search_response("q1"),
            _llm_search_response("q2"),
            _llm_search_response("q3"),   # 3rd search hits MAX_STEPS
            _llm_finalize_response(),      # force_finalize triggers this
        ])
        result = agent.run_react_loop("machine learning")
        assert isinstance(result, DialogueModel)

    def test_search_tool_called_at_most_max_steps_times(self):
        search_mock = MagicMock()
        search_mock.query.return_value = ["snippet"]
        llm_mock = MagicMock()
        # Always return search action
        llm_mock.call.side_effect = [
            _llm_search_response("q1"),
            _llm_search_response("q2"),
            _llm_search_response("q3"),
            _llm_finalize_response(),
        ]
        agent = AgentCore(
            llm_client=llm_mock,
            search_tool=search_mock,
            memory=SessionMemory(),
            cost_tracker=CostTracker(),
            validator=DialogueValidator(),
        )
        agent.run_react_loop("topic")
        assert search_mock.query.call_count <= 3


class TestBudgetGuard:
    def test_force_finalize_on_budget_exceeded(self, monkeypatch):
        monkeypatch.setenv("LLM_COST_INPUT_PER_1K", "1.0")
        monkeypatch.setenv("LLM_COST_OUTPUT_PER_1K", "0.0")
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "0.05")  # tiny limit

        llm_mock = MagicMock()
        # First call returns search action (and costs > $0.05 via tracking)
        llm_mock.call.side_effect = [
            _llm_search_response(),  # triggers BudgetExceeded on track()
            _llm_finalize_response(),  # force_finalize path
        ]

        cost_tracker = CostTracker()
        agent = AgentCore(
            llm_client=llm_mock,
            search_tool=MagicMock(query=MagicMock(return_value=["snippet"])),
            memory=SessionMemory(),
            cost_tracker=cost_tracker,
            validator=DialogueValidator(),
        )
        # Should not raise — pipeline continues with force_finalize
        result = agent.run_react_loop("neural networks")
        assert isinstance(result, DialogueModel)


class TestSearchUnavailable:
    def test_loop_continues_with_unavailable_observation(self):
        search_mock = MagicMock()
        search_mock.query.return_value = ["search unavailable"]
        agent = AgentCore(
            llm_client=MagicMock(side_effect=[
                _llm_search_response(),
                _llm_finalize_response(),
            ]),
            search_tool=search_mock,
            memory=SessionMemory(),
            cost_tracker=CostTracker(),
            validator=DialogueValidator(),
        )
        # patch .call attribute properly
        llm_mock = MagicMock()
        llm_mock.call.side_effect = [_llm_search_response(), _llm_finalize_response()]
        agent._llm = llm_mock
        result = agent.run_react_loop("deep learning")
        assert isinstance(result, DialogueModel)


class TestLLMUnavailable:
    def test_raises_llm_unavailable_when_llm_fails(self):
        llm_mock = MagicMock()
        llm_mock.call.side_effect = LLMUnavailableError("offline")
        agent = AgentCore(
            llm_client=llm_mock,
            search_tool=MagicMock(),
            memory=SessionMemory(),
            cost_tracker=CostTracker(),
            validator=DialogueValidator(),
        )
        with pytest.raises(LLMUnavailableError):
            agent.run_react_loop("topic")
