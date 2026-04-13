from __future__ import annotations

# load_dotenv() MUST run before any project imports that read os.environ
from dotenv import load_dotenv
load_dotenv()

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eduvid",
        description="EduVid Factory — agentic educational video creation",
    )
    parser.add_argument("topic", help="Topic for the educational video (e.g. 'Gradient Boosting')")
    parser.add_argument("--style", default="", metavar="HINT",
                        help="Style hint (e.g. 'for beginners', 'technical')")
    parser.add_argument("--model", default=None, metavar="MODEL",
                        help="Override LLM_MODEL environment variable")
    parser.add_argument("--output", default="output", metavar="DIR",
                        help="Output directory for the MP4 (default: output/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run agent only; skip TTS and video composition")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING"],
                        help="Logging verbosity (default: INFO)")
    args = parser.parse_args(argv)

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    # Import project modules AFTER load_dotenv() and arg parsing
    from src.pipeline_orchestrator import PipelineOrchestrator
    from src.utils.exceptions import ConfigurationError, EduVidError

    try:
        orchestrator = PipelineOrchestrator(
            output_dir=args.output,
            dry_run=args.dry_run,
            log_level=args.log_level,
        )
        output = orchestrator.run(topic=args.topic, style_hint=args.style)
        if not args.dry_run:
            print(f"Video created: {output}")
        return 0

    except ConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    except EduVidError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
