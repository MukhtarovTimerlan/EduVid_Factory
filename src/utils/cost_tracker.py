import os

from src.utils.exceptions import BudgetExceededError


class CostTracker:
    """Tracks LLM token usage and cumulative cost for one pipeline session."""

    def __init__(self) -> None:
        self._cost_per_1k_input = float(os.environ.get("LLM_COST_INPUT_PER_1K", "0.00015"))
        self._cost_per_1k_output = float(os.environ.get("LLM_COST_OUTPUT_PER_1K", "0.0006"))
        self._hard_limit = float(os.environ.get("AGENT_COST_LIMIT_USD", "2.0"))
        self._session_cost: float = 0.0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0

    def track(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Record token usage and return the incremental cost (USD).
        Raises BudgetExceededError if total session cost exceeds the hard limit.
        """
        cost = (prompt_tokens / 1000) * self._cost_per_1k_input + \
               (completion_tokens / 1000) * self._cost_per_1k_output
        self._session_cost += cost
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        if self._session_cost >= self._hard_limit:
            raise BudgetExceededError(
                f"Session cost ${self._session_cost:.4f} exceeded hard limit ${self._hard_limit:.2f}"
            )
        return cost

    def check_budget(self) -> None:
        """Raise BudgetExceededError if already at or over limit (called before LLM call)."""
        if self._session_cost >= self._hard_limit:
            raise BudgetExceededError(
                f"Session cost ${self._session_cost:.4f} >= limit ${self._hard_limit:.2f}"
            )

    @property
    def session_cost(self) -> float:
        return self._session_cost

    def get_session_tokens(self) -> dict:
        return {"prompt": self._prompt_tokens, "completion": self._completion_tokens}

    def reset(self) -> None:
        self._session_cost = 0.0
        self._prompt_tokens = 0
        self._completion_tokens = 0
