from src.utils.validators import DialogueLine, DialogueModel


class ScriptGenerator:
    """Thin adapter: converts DialogueModel → list[DialogueLine] for TTS."""

    def __init__(self, logger=None) -> None:
        self._logger = logger

    def prepare(self, dialogue: DialogueModel) -> list[DialogueLine]:
        """Return the dialogue lines ready for audio synthesis."""
        lines = dialogue.lines
        if self._logger:
            self._logger.info(f"ScriptGenerator: prepared {len(lines)} lines")
        return lines
