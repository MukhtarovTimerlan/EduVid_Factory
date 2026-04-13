from __future__ import annotations

import copy
import json
import os
import re
from enum import Enum, auto
from typing import Any

try:
    import tiktoken
    _enc = tiktoken.encoding_for_model("gpt-4o-mini")
except KeyError:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")


from src.agent.llm_client import LLMClient, LLMResponse
from src.agent.memory import SessionMemory, Step
from src.agent.prompt_templates import (
    CORRECTION_HINT,
    FALLBACK_DIALOGUE_TEMPLATE,
    FORCE_FINALIZE_HINT,
    SCHEMA_EXAMPLE,
    SYSTEM_PROMPT,
    build_user_message,
)
from src.tools.search import SearchTool
from src.utils.cost_tracker import CostTracker
from src.utils.exceptions import BudgetExceededError, LLMUnavailableError, ParseError, ValidationError
from src.utils.validators import DialogueLine, DialogueModel, DialogueValidator

_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "3"))
_MAX_PARSE_RETRY = 2
_MAX_VAL_RETRY = 2
_TOKEN_BUDGET = int(os.environ.get("AGENT_TOKEN_BUDGET", "8000"))

_ACTION_SEARCH_RE = re.compile(
    r"ACTION:\s*search\s*\nQUERY:\s*(.+)", re.IGNORECASE | re.DOTALL
)
_ACTION_FINALIZE_RE = re.compile(
    r"ACTION:\s*finalize\s*\nDIALOGUE:\s*(\{.+)", re.IGNORECASE | re.DOTALL
)


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


class _State(Enum):
    BUILD_PROMPT = auto()
    LLM_CALL = auto()
    PARSE = auto()
    SEARCH = auto()
    VALIDATE = auto()
    FORCE_FINALIZE = auto()
    FALLBACK_DIALOGUE = auto()
    DONE = auto()
    ABORT = auto()


class AgentCore:
    """ReAct agent that iteratively searches and generates educational dialogue."""

    def __init__(
        self,
        llm_client: LLMClient,
        search_tool: SearchTool,
        memory: SessionMemory,
        cost_tracker: CostTracker,
        validator: DialogueValidator,
        logger=None,
    ) -> None:
        self._llm = llm_client
        self._search = search_tool
        self._memory = memory
        self._cost = cost_tracker
        self._validator = validator
        self._logger = logger

    def run_react_loop(self, topic: str, style_hint: str = "") -> DialogueModel:
        """
        Execute the ReAct loop (max _MAX_STEPS search iterations).
        Returns a validated DialogueModel.
        Raises LLMUnavailableError if LLM is completely unreachable.
        """
        self._memory.clear()

        step = 0
        parse_retry = 0
        val_retry = 0
        correction_hint = ""
        schema_example = ""
        force_finalize = False
        force_finalize_reason = ""

        state = _State.BUILD_PROMPT
        messages: list[dict] = []
        raw_response = ""
        parsed_action: str = ""
        parsed_payload: Any = None
        dialogue: DialogueModel | None = None

        while state not in (_State.DONE, _State.ABORT):

            # ── Budget guard (wraps the full loop body) ────────────────────
            try:

                if state == _State.BUILD_PROMPT:
                    self._log("info", f"Agent step {step + 1}/{_MAX_STEPS} started")
                    # Skip budget check when already in force-finalize mode to avoid infinite loop
                    if not force_finalize:
                        try:
                            self._cost.check_budget()
                        except BudgetExceededError:
                            force_finalize_reason = "budget_exceeded"
                            state = _State.FORCE_FINALIZE
                            continue

                    user_msg = build_user_message(
                        topic=topic,
                        style_hint=style_hint,
                        history=self._memory.get_history(),
                        step_n=step + 1,
                        max_steps=_MAX_STEPS,
                        correction_hint=correction_hint,
                        schema_example=schema_example,
                        force_finalize=force_finalize,
                    )

                    # Token budget check + truncation
                    system_tokens = _count_tokens(SYSTEM_PROMPT)
                    user_tokens = _count_tokens(user_msg)
                    history_tokens = self._memory.token_count(_count_tokens)

                    total = system_tokens + user_tokens + history_tokens
                    if total > _TOKEN_BUDGET:
                        removed = self._memory.truncate(keep_last_n_pairs=2)
                        self._log("info", f"Memory truncated: removed {removed} pairs")
                        user_msg = build_user_message(
                            topic=topic,
                            style_hint=style_hint,
                            history=self._memory.get_history(),
                            step_n=step + 1,
                            max_steps=_MAX_STEPS,
                            correction_hint=correction_hint,
                            schema_example=schema_example,
                            force_finalize=force_finalize,
                        )
                        total = system_tokens + _count_tokens(user_msg) + self._memory.token_count(_count_tokens)

                        if total > _TOKEN_BUDGET:
                            removed = self._memory.truncate(keep_last_n_pairs=1)
                            self._log("info", f"Memory truncated again: removed {removed} pairs")
                            user_msg = build_user_message(
                                topic=topic,
                                style_hint=style_hint,
                                history=self._memory.get_history(),
                                step_n=step + 1,
                                max_steps=_MAX_STEPS,
                                correction_hint=correction_hint,
                                schema_example=schema_example,
                                force_finalize=force_finalize,
                            )

                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ]
                    self._log("info", f"Prompt built | tokens≈{system_tokens + _count_tokens(user_msg)}")
                    correction_hint = ""
                    schema_example = ""
                    state = _State.LLM_CALL

                elif state == _State.LLM_CALL:
                    try:
                        resp: LLMResponse = self._llm.call(messages)
                        self._cost.track(resp.prompt_tokens, resp.completion_tokens)
                        raw_response = resp.content
                        state = _State.PARSE
                    except BudgetExceededError:
                        if force_finalize:
                            # Budget exceeded even during force-finalize LLM call — use fallback
                            state = _State.FALLBACK_DIALOGUE
                        else:
                            force_finalize_reason = "budget_exceeded"
                            state = _State.FORCE_FINALIZE
                    except LLMUnavailableError:
                        state = _State.ABORT

                elif state == _State.PARSE:
                    try:
                        parsed_action, parsed_payload = self._parse_response(raw_response)
                        parse_retry = 0
                        if parsed_action == "search":
                            state = _State.SEARCH
                        else:
                            state = _State.VALIDATE
                    except ParseError as e:
                        parse_retry += 1
                        self._log("warning", f"ParseError retry {parse_retry}/{_MAX_PARSE_RETRY}: {e}")
                        if parse_retry <= _MAX_PARSE_RETRY:
                            correction_hint = CORRECTION_HINT
                            state = _State.BUILD_PROMPT
                        else:
                            force_finalize_reason = "parse_failed"
                            state = _State.FORCE_FINALIZE

                elif state == _State.SEARCH:
                    step += 1
                    self._log("info", f'Agent action=search | query="{parsed_payload}"')
                    self._memory.add_step(
                        Step(role="action", content=parsed_payload, tool="search", step_n=step)
                    )
                    snippets = self._search.query(parsed_payload)
                    obs = "\n".join(snippets)
                    self._memory.add_step(
                        Step(role="observation", content=obs, step_n=step)
                    )

                    if step >= _MAX_STEPS:
                        force_finalize_reason = "iteration_limit"
                        state = _State.FORCE_FINALIZE
                    else:
                        state = _State.BUILD_PROMPT

                elif state == _State.VALIDATE:
                    raw_json = (
                        json.dumps(parsed_payload)
                        if isinstance(parsed_payload, dict)
                        else str(parsed_payload)
                    )
                    try:
                        dialogue = self._validator.validate(raw_json)
                        warnings = self._validator.sanity_check(dialogue, topic)
                        for w in warnings:
                            self._log("warning", w)
                        self._log("info", f"Agent action=finalize | dialogue_lines={len(dialogue.lines)}")
                        state = _State.DONE
                    except ValidationError as e:
                        val_retry += 1
                        self._log("warning", f"ValidationError retry {val_retry}/{_MAX_VAL_RETRY}: {e}")
                        if val_retry <= _MAX_VAL_RETRY:
                            schema_example = SCHEMA_EXAMPLE
                            state = _State.BUILD_PROMPT
                        else:
                            state = _State.FALLBACK_DIALOGUE

                elif state == _State.FORCE_FINALIZE:
                    self._log("warning", f"Force finalize triggered | reason={force_finalize_reason}")
                    force_finalize = True
                    correction_hint = FORCE_FINALIZE_HINT
                    # If we arrived here after a parse failure with retries exhausted,
                    # go directly to FALLBACK to avoid infinite loop
                    if force_finalize_reason == "parse_failed" and parse_retry > _MAX_PARSE_RETRY:
                        state = _State.FALLBACK_DIALOGUE
                    else:
                        state = _State.BUILD_PROMPT

                elif state == _State.FALLBACK_DIALOGUE:
                    self._log("warning", "Using fallback dialogue | reason=validation_failed_after_retry")
                    lines = [
                        DialogueLine(
                            speaker=item["speaker"],
                            text=item["text"].format(topic=topic),
                        )
                        for item in copy.deepcopy(FALLBACK_DIALOGUE_TEMPLATE)
                    ]
                    dialogue = DialogueModel(lines=lines)
                    state = _State.DONE

            except BudgetExceededError:
                if force_finalize:
                    # Already forcing — budget still exceeded after finalize attempt, use fallback
                    state = _State.FALLBACK_DIALOGUE
                else:
                    force_finalize_reason = "budget_exceeded"
                    state = _State.FORCE_FINALIZE

        if state == _State.ABORT:
            self._memory.clear()
            raise LLMUnavailableError("Agent aborted: LLM is unavailable")

        self._memory.clear()
        assert dialogue is not None
        return dialogue

    # ── private ───────────────────────────────────────────────────────────────

    def _parse_response(self, raw: str) -> tuple[str, Any]:
        """
        Parse LLM response into (action, payload).
        Raises ParseError if format is unrecognised.
        """
        raw = raw.strip()

        m = _ACTION_SEARCH_RE.search(raw)
        if m:
            query = m.group(1).strip().splitlines()[0].strip()
            return "search", query

        m = _ACTION_FINALIZE_RE.search(raw)
        if m:
            json_str = m.group(1).strip()
            # Strip trailing content after the JSON object
            try:
                obj = json.loads(json_str)
                return "finalize", obj
            except json.JSONDecodeError:
                # Try to extract just the first complete JSON object
                try:
                    decoder = json.JSONDecoder()
                    obj, _ = decoder.raw_decode(json_str)
                    return "finalize", obj
                except json.JSONDecodeError as e:
                    raise ParseError(f"DIALOGUE JSON is invalid: {e}") from e

        raise ParseError(
            f"Response does not match expected format (ACTION: search/finalize). "
            f"Got: {raw[:200]!r}"
        )

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
