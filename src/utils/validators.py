import json
from typing import Literal

from pydantic import BaseModel, field_validator

from src.utils.exceptions import ValidationError


class DialogueLine(BaseModel):
    speaker: Literal["A", "B"]
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty")
        return v


class DialogueModel(BaseModel):
    lines: list[DialogueLine]

    @field_validator("lines")
    @classmethod
    def check_length(cls, v: list) -> list:
        if len(v) < 2:
            raise ValueError("dialogue must have at least 2 lines")
        if len(v) > 20:
            raise ValueError("dialogue must have at most 20 lines")
        return v


_ARTIFACTS = ("ACTION:", "QUERY:", "```")


class DialogueValidator:
    def validate(self, raw_json: str) -> DialogueModel:
        """
        Parse and validate dialogue JSON.
        Raises ValidationError with details on failure.
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}") from e

        try:
            return DialogueModel.model_validate(data)
        except Exception as e:
            raise ValidationError(f"Schema error: {e}") from e

    def sanity_check(self, dialogue: DialogueModel, topic: str) -> list[str]:
        """
        Soft checks — returns a list of warning strings (not abort).
        Checks: topic mention, no LLM artifacts, line length 50–300 chars.
        """
        warnings: list[str] = []
        full_text = " ".join(line.text for line in dialogue.lines)

        if topic.lower() not in full_text.lower():
            warnings.append(f"sanity: topic '{topic}' not mentioned in dialogue")

        for artifact in _ARTIFACTS:
            if artifact in full_text:
                warnings.append(f"sanity: artifact '{artifact}' found in dialogue text")

        lengths = [len(line.text) for line in dialogue.lines]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
        if not (50 <= avg_len <= 300):
            warnings.append(f"sanity: average line length {avg_len:.0f} chars is outside [50, 300]")

        return warnings
