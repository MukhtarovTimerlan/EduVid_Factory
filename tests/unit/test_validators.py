import json
import pytest

from src.utils.exceptions import ValidationError
from src.utils.validators import DialogueModel, DialogueValidator


@pytest.fixture
def validator():
    return DialogueValidator()


def _valid_json(n: int = 3) -> str:
    lines = [{"speaker": "A" if i % 2 == 0 else "B", "text": f"Line {i} text."} for i in range(n)]
    return json.dumps({"lines": lines})


class TestValidate:
    def test_valid_dialogue(self, validator):
        result = validator.validate(_valid_json(4))
        assert isinstance(result, DialogueModel)
        assert len(result.lines) == 4

    def test_too_few_lines_raises(self, validator):
        with pytest.raises(ValidationError, match="at least 2"):
            validator.validate(json.dumps({"lines": [{"speaker": "A", "text": "hi"}]}))

    def test_too_many_lines_raises(self, validator):
        with pytest.raises(ValidationError):
            validator.validate(_valid_json(21))

    def test_invalid_speaker_raises(self, validator):
        data = {"lines": [{"speaker": "C", "text": "hi"}, {"speaker": "A", "text": "ok"}]}
        with pytest.raises(ValidationError):
            validator.validate(json.dumps(data))

    def test_empty_text_raises(self, validator):
        data = {"lines": [{"speaker": "A", "text": ""}, {"speaker": "B", "text": "ok"}]}
        with pytest.raises(ValidationError):
            validator.validate(json.dumps(data))

    def test_invalid_json_raises(self, validator):
        with pytest.raises(ValidationError, match="Invalid JSON"):
            validator.validate("not json at all")

    def test_missing_lines_key_raises(self, validator):
        with pytest.raises(ValidationError):
            validator.validate(json.dumps({"dialogue": []}))


class TestSanityCheck:
    def test_no_warnings_on_clean_dialogue(self, validator):
        dialogue = validator.validate(_valid_json(4))
        # Build dialogue with topic mention and correct length
        import json as _json
        raw = _json.dumps({
            "lines": [
                {"speaker": "A", "text": "Today we explore gradient boosting in detail."},
                {"speaker": "B", "text": "That sounds great, tell me more about gradient boosting."},
            ]
        })
        d = validator.validate(raw)
        warnings = validator.sanity_check(d, "gradient boosting")
        assert not warnings

    def test_warns_on_missing_topic(self, validator):
        d = validator.validate(_valid_json(2))
        warnings = validator.sanity_check(d, "quantum_physics_xyz")
        assert any("not mentioned" in w for w in warnings)

    def test_warns_on_artifact(self, validator):
        raw = json.dumps({
            "lines": [
                {"speaker": "A", "text": "ACTION: search something here."},
                {"speaker": "B", "text": "OK, got it."},
            ]
        })
        d = validator.validate(raw)
        warnings = validator.sanity_check(d, "something")
        assert any("ACTION:" in w for w in warnings)
