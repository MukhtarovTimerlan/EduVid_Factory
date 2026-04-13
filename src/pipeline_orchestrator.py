import os
import shutil
from pathlib import Path
from uuid import uuid4

from src.agent.agent_core import AgentCore
from src.agent.llm_client import LLMClient
from src.agent.memory import SessionMemory
from src.composition.video_composer import VideoComposer
from src.generation.asset_selector import AssetSelector
from src.generation.audio_generator import AudioGenerator
from src.generation.script_generator import ScriptGenerator
from src.tools.search import SearchTool
from src.utils.cost_tracker import CostTracker
from src.utils.exceptions import (
    AssetsMissingError,
    ConfigurationError,
    LLMUnavailableError,
    PipelineError,
    VideoCompositionError,
)
from src.utils.fact_checker import FactChecker
from src.utils.logger import setup_logger
from src.utils.validators import DialogueValidator

_REQUIRED_ENV_VARS = [
    "ROUTERAI_BASE_URL",
    "ROUTERAI_API_KEY",
]


class PipelineOrchestrator:
    """Coordinates the full EduVid creation pipeline."""

    def __init__(
        self,
        output_dir: str = "output",
        dry_run: bool = False,
        log_level: str = "INFO",
    ) -> None:
        self._output_dir = Path(output_dir)
        self._dry_run = dry_run
        self._log_level = log_level
        self._validate_config()

    def run(self, topic: str, style_hint: str = "") -> Path:
        """
        Execute the full pipeline for a given topic.
        Returns the path to the output MP4 (or /dev/null for dry_run).
        Raises: AssetsMissingError, LLMUnavailableError, PipelineError.
        """
        run_id = str(uuid4())[:8]
        logger = setup_logger("pipeline", run_id=run_id, log_level=self._log_level)

        logger.info(f'Pipeline started | topic="{topic}" style="{style_hint}"')

        # Validate assets before creating temp dir
        if not self._dry_run:
            asset_selector = AssetSelector(logger=logger)
            self._check_assets(asset_selector)

        temp_dir = Path(os.environ.get("TEMP_DIR", "temp")) / run_id
        temp_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

        import time
        t0 = time.monotonic()

        try:
            # Build components with shared logger
            cost_tracker = CostTracker()
            llm_client = LLMClient(logger=logger)
            search_tool = SearchTool(logger=logger)
            memory = SessionMemory()
            validator = DialogueValidator()
            agent = AgentCore(
                llm_client=llm_client,
                search_tool=search_tool,
                memory=memory,
                cost_tracker=cost_tracker,
                validator=validator,
                logger=logger,
            )
            script_gen = ScriptGenerator(logger=logger)

            # ── Agent: ReAct loop ─────────────────────────────────────────
            dialogue = agent.run_react_loop(topic, style_hint)

            # ── Fact-check (LLM-as-Judge) ─────────────────────────────────
            fact_checker = FactChecker(llm_client=llm_client, logger=logger)
            fact_warnings = fact_checker.check(dialogue, topic)
            if fact_warnings:
                logger.warning(f"Fact-check found {len(fact_warnings)} issue(s) — continuing anyway")

            # ── Dry-run: stop after agent ──────────────────────────────────
            if self._dry_run:
                logger.info(f"Dry-run complete | dialogue_lines={len(dialogue.lines)}")
                for line in dialogue.lines:
                    logger.info(f"  [{line.speaker}] {line.text}")
                self._cleanup(temp_dir)
                return Path("/dev/null")

            # ── TTS ───────────────────────────────────────────────────────
            lines = script_gen.prepare(dialogue)
            audio_gen = AudioGenerator(logger=logger)
            audio_path = audio_gen.synthesize(lines, temp_dir)

            # ── Assets ────────────────────────────────────────────────────
            bg, char_a, char_b = asset_selector.pick()

            # ── Video composition ─────────────────────────────────────────
            self._output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self._output_dir / f"video_{run_id}.mp4"
            composer = VideoComposer(logger=logger)
            composer.assemble(bg, char_a, char_b, audio_path, output_path)

        except (AssetsMissingError, LLMUnavailableError):
            self._cleanup(temp_dir)
            raise
        except VideoCompositionError:
            self._cleanup(temp_dir)
            raise
        except Exception as e:
            self._cleanup(temp_dir)
            raise PipelineError(stage="unknown", cause=e) from e
        else:
            self._cleanup(temp_dir)

        elapsed = time.monotonic() - t0
        logger.info(
            f"Pipeline finished | output={output_path} "
            f"elapsed={elapsed:.1f}s total_cost=${cost_tracker.session_cost:.4f}"
        )
        return output_path

    # ── private ───────────────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in the values."
            )

    def _check_assets(self, asset_selector: AssetSelector) -> None:
        """Pre-flight check: call pick() to validate assets exist before any API call."""
        asset_selector.pick()

    def _cleanup(self, temp_dir: Path) -> None:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
