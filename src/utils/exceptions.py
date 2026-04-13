class EduVidError(Exception):
    """Base exception for all EduVid Factory errors."""


class ConfigurationError(EduVidError):
    """Missing or invalid environment variable / configuration."""


class AssetsMissingError(EduVidError):
    """Required asset directories are empty."""


class LLMUnavailableError(EduVidError):
    """LLM API is unreachable after retries."""


class BudgetExceededError(EduVidError):
    """Session cost exceeded the hard limit."""


class ParseError(EduVidError):
    """LLM response could not be parsed into a valid action."""


class ValidationError(EduVidError):
    """Dialogue JSON failed schema validation."""


class SearchConfigError(EduVidError):
    """Search API key/config is invalid (HTTP 4xx). No retry."""


class AudioError(EduVidError):
    """All TTS lines failed — cannot produce audio."""


class AudioConfigError(AudioError):
    """ElevenLabs API key/config is invalid (HTTP 401). No retry."""


class VideoCompositionError(EduVidError):
    """MoviePy failed to compose the final video."""


class PipelineError(EduVidError):
    """Wraps an unexpected error with stage context."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"Pipeline failed at stage '{stage}': {cause}")
        self.stage = stage
        self.cause = cause
