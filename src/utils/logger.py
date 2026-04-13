import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SENSITIVE_KEYS = frozenset(["api_key", "authorization", "x-api-key", "bearer"])

LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
LOG_DIR = os.environ.get("LOG_DIR", "logs")

_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s [%(run_id)s] - %(message)s"
_handlers_initialised = False


def _ensure_log_dir() -> None:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


def _get_file_handler() -> RotatingFileHandler:
    _ensure_log_dir()
    handler = RotatingFileHandler(
        Path(LOG_DIR) / "pipeline.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler


def _get_stream_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler


def setup_logger(name: str, run_id: str = "", log_level: str = "INFO") -> logging.LoggerAdapter:
    """
    Return a LoggerAdapter that injects run_id into every log record.
    Safe to call multiple times — handlers are added only once per logger name.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.addHandler(_get_file_handler())
        logger.addHandler(_get_stream_handler())
        logger.propagate = False

    logger.setLevel(level)
    return logging.LoggerAdapter(logger, {"run_id": run_id})


def sanitize_for_log(data: dict) -> dict:
    """Replace values of sensitive keys with '***'."""
    result = {}
    for k, v in data.items():
        if k.lower() in _SENSITIVE_KEYS:
            result[k] = "***"
        else:
            result[k] = v
    return result
