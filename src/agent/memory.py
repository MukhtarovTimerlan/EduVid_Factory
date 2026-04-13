import os
from dataclasses import dataclass, field
from typing import Callable, Literal

_TOKEN_BUDGET = int(os.environ.get("AGENT_TOKEN_BUDGET", "8000"))
_SYSTEM_RESERVE = 800
_INSTRUCTION_RESERVE = 200
AVAILABLE_FOR_HISTORY = _TOKEN_BUDGET - _SYSTEM_RESERVE - _INSTRUCTION_RESERVE


@dataclass
class Step:
    role: Literal["thought", "action", "observation"]
    content: str
    tool: str | None = None
    step_n: int = 0


class SessionMemory:
    """In-memory session history with token budget management."""

    def __init__(self) -> None:
        self._steps: list[Step] = []

    def add_step(self, step: Step) -> None:
        self._steps.append(step)

    def get_history(self) -> list[Step]:
        return list(self._steps)

    def token_count(self, tokenizer_fn: Callable[[str], int]) -> int:
        return sum(tokenizer_fn(s.content) for s in self._steps)

    def truncate(self, keep_last_n_pairs: int = 2) -> int:
        """
        Remove oldest (action + observation) pairs from history.
        Thought steps are never removed.
        Returns the number of pairs removed.
        """
        # Collect indices of (action, observation) consecutive pairs
        pairs: list[tuple[int, int]] = []
        i = 0
        while i < len(self._steps) - 1:
            if (
                self._steps[i].role == "action"
                and self._steps[i + 1].role == "observation"
            ):
                pairs.append((i, i + 1))
                i += 2
            else:
                i += 1

        pairs_to_remove = len(pairs) - keep_last_n_pairs
        if pairs_to_remove <= 0:
            return 0

        # Collect flat indices to delete (oldest first)
        indices_to_delete: set[int] = set()
        for pair_idx, pair in enumerate(pairs):
            if pair_idx < pairs_to_remove:
                indices_to_delete.update(pair)

        self._steps = [s for idx, s in enumerate(self._steps) if idx not in indices_to_delete]
        return pairs_to_remove

    def clear(self) -> None:
        self._steps.clear()
