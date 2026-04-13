from src.utils.validators import DialogueModel

_FACT_CHECK_PROMPT = """\
You are a factual accuracy reviewer for short educational dialogues.

Topic: {topic}

Dialogue:
{dialogue}

Review the dialogue above for factual errors related to the topic.
Be concise. If there are NO factual errors, respond with exactly: OK
If there ARE errors, list them briefly, one per line, starting with "ERROR:".
Do NOT comment on style, length, or format — only factual accuracy."""


class FactChecker:
    """
    LLM-as-Judge: verifies factual accuracy of a generated dialogue.
    Always returns a list of warning strings (never raises, never aborts).
    """

    def __init__(self, llm_client, logger=None) -> None:
        self._llm = llm_client
        self._logger = logger

    def check(self, dialogue: DialogueModel, topic: str) -> list[str]:
        """
        Ask the LLM to fact-check the dialogue.
        Returns list of warning strings (empty = no issues found).
        """
        dialogue_text = "\n".join(
            f"[{line.speaker}]: {line.text}" for line in dialogue.lines
        )
        prompt = _FACT_CHECK_PROMPT.format(topic=topic, dialogue=dialogue_text)

        try:
            from src.agent.llm_client import LLMResponse  # noqa: F401 — ensure importable
            resp = self._llm.call(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
            )
            result = resp.content.strip()

            if result.upper() == "OK":
                self._log("info", "Fact-check passed: no errors found")
                return []

            errors = [
                line.strip()
                for line in result.splitlines()
                if line.strip().upper().startswith("ERROR:")
            ]
            if errors:
                for e in errors:
                    self._log("warning", f"Fact-check: {e}")
                return errors

            # LLM responded with something unexpected — log as info, don't abort
            self._log("info", f"Fact-check uncertain response: {result[:200]}")
            return []

        except Exception as e:  # noqa: BLE001
            self._log("warning", f"Fact-check skipped (LLM error): {e}")
            return []

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
