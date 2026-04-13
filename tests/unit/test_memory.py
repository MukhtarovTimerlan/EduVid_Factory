import pytest

from src.agent.memory import SessionMemory, Step


def _tok(text: str) -> int:
    return len(text.split())


def _make_steps(n_pairs: int) -> list[Step]:
    steps = []
    for i in range(1, n_pairs + 1):
        steps.append(Step(role="thought", content=f"thought {i}", step_n=i))
        steps.append(Step(role="action", content=f"query {i}", tool="search", step_n=i))
        steps.append(Step(role="observation", content=f"result {i}", step_n=i))
    return steps


class TestSessionMemory:
    def test_add_and_get(self):
        mem = SessionMemory()
        mem.add_step(Step(role="thought", content="hello"))
        assert len(mem.get_history()) == 1

    def test_clear(self):
        mem = SessionMemory()
        for s in _make_steps(2):
            mem.add_step(s)
        mem.clear()
        assert mem.get_history() == []

    def test_token_count(self):
        mem = SessionMemory()
        mem.add_step(Step(role="thought", content="hello world"))
        mem.add_step(Step(role="observation", content="foo bar baz"))
        assert mem.token_count(_tok) == 5

    def test_truncate_keeps_last_n_pairs(self):
        mem = SessionMemory()
        for s in _make_steps(3):
            mem.add_step(s)
        # 3 pairs: (thought, action, observation) × 3 = 9 steps
        removed = mem.truncate(keep_last_n_pairs=2)
        assert removed == 1
        history = mem.get_history()
        # Action+observation from pair 1 should be removed; thought stays
        actions = [s for s in history if s.role == "action"]
        assert len(actions) == 2
        obs = [s for s in history if s.role == "observation"]
        assert len(obs) == 2
        # All thoughts must still be present
        thoughts = [s for s in history if s.role == "thought"]
        assert len(thoughts) == 3

    def test_truncate_no_op_when_pairs_lte_keep(self):
        mem = SessionMemory()
        for s in _make_steps(2):
            mem.add_step(s)
        removed = mem.truncate(keep_last_n_pairs=3)
        assert removed == 0
        assert len(mem.get_history()) == 6

    def test_truncate_keeps_one_pair(self):
        mem = SessionMemory()
        for s in _make_steps(3):
            mem.add_step(s)
        removed = mem.truncate(keep_last_n_pairs=1)
        assert removed == 2
        actions = [s for s in mem.get_history() if s.role == "action"]
        assert len(actions) == 1
        # The kept action should be the last one (step_n=3)
        assert actions[0].step_n == 3
