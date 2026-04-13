import os
import pytest

from src.utils.exceptions import BudgetExceededError
from src.utils.cost_tracker import CostTracker


class TestCostTracker:
    def test_track_returns_incremental_cost(self, monkeypatch):
        monkeypatch.setenv("LLM_COST_INPUT_PER_1K", "0.001")
        monkeypatch.setenv("LLM_COST_OUTPUT_PER_1K", "0.002")
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
        tracker = CostTracker()
        cost = tracker.track(1000, 500)
        assert abs(cost - (0.001 + 0.001)) < 1e-9

    def test_accumulates_cost(self, monkeypatch):
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
        tracker = CostTracker()
        tracker.track(1000, 0)
        tracker.track(1000, 0)
        assert tracker.session_cost > 0

    def test_raises_on_exceeded_limit(self, monkeypatch):
        monkeypatch.setenv("LLM_COST_INPUT_PER_1K", "1.0")
        monkeypatch.setenv("LLM_COST_OUTPUT_PER_1K", "0.0")
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "1.5")
        tracker = CostTracker()
        tracker.track(1000, 0)  # costs $1.00
        with pytest.raises(BudgetExceededError):
            tracker.track(1000, 0)  # would put total at $2.00 > $1.50

    def test_check_budget_raises_when_at_limit(self, monkeypatch):
        monkeypatch.setenv("LLM_COST_INPUT_PER_1K", "2.0")
        monkeypatch.setenv("LLM_COST_OUTPUT_PER_1K", "0.0")
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "1.5")
        tracker = CostTracker()
        with pytest.raises(BudgetExceededError):
            tracker.track(1000, 0)  # immediately exceeds $1.5

    def test_check_budget_ok_when_under_limit(self, monkeypatch):
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
        tracker = CostTracker()
        tracker.check_budget()  # should not raise

    def test_reset(self, monkeypatch):
        monkeypatch.setenv("AGENT_COST_LIMIT_USD", "10.0")
        tracker = CostTracker()
        tracker.track(1000, 1000)
        tracker.reset()
        assert tracker.session_cost == 0.0
