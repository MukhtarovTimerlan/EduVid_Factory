import asyncio
import os
import time
from pathlib import Path

from src.utils.exceptions import AudioError
from src.utils.validators import DialogueLine

_RETRY_BACKOFF = (1, 2, 4)

# Silero TTS — genuine different Russian female voices
_SILERO_VOICE_A = "xenia"   # clear, energetic female
_SILERO_VOICE_B = "baya"    # warmer, softer female
_SILERO_SAMPLE_RATE = 48000

# Edge-tts fallback — same voice, different prosody
_EDGE_VOICE = "ru-RU-SvetlanaNeural"
_EDGE_PROSODY = {
    "A": {"rate": "+0%",  "pitch": "+0Hz"},
    "B": {"rate": "-15%", "pitch": "+12Hz"},
}


class AudioGenerator:
    """
    Primary: Silero TTS (local, torch.hub) — two distinct Russian female voices.
    Fallback: edge-tts with per-speaker prosody if torch is unavailable.
    """

    def __init__(self, logger=None) -> None:
        self._voice_a = os.environ.get("TTS_VOICE_A", _SILERO_VOICE_A)
        self._voice_b = os.environ.get("TTS_VOICE_B", _SILERO_VOICE_B)
        self._edge_voice = os.environ.get("EDGE_TTS_VOICE", _EDGE_VOICE)
        self._logger = logger
        self._silero_model = None   # lazy: loaded on first use
        self._silero_ok: bool | None = None  # None=untested, True=works, False=use edge

    def synthesize(self, lines: list[DialogueLine], output_dir: Path) -> Path:
        self._log("info", f"TTS started | lines={len(lines)}")
        segment_paths: list[Path] = []

        for i, line in enumerate(lines):
            path = self._synthesize_line(line, output_dir, index=i, total=len(lines))
            if path is not None:
                segment_paths.append(path)

        if not segment_paths:
            raise AudioError("All TTS lines failed — cannot produce audio")

        return self._concat(segment_paths, output_dir / "audio.mp3")

    # ── private ───────────────────────────────────────────────────────────────

    def _synthesize_line(
        self, line: DialogueLine, output_dir: Path, index: int, total: int
    ) -> Path | None:
        voice = self._voice_a if line.speaker == "A" else self._voice_b
        self._log("info", f"TTS line {index + 1}/{total} | speaker={line.speaker} chars={len(line.text)}")

        for attempt, delay in enumerate(_RETRY_BACKOFF, 1):
            try:
                if self._silero_ok is not False:
                    path = output_dir / f"line_{index:03d}.wav"
                    ok = self._synthesize_silero(line.text, voice, path)
                    if ok:
                        self._silero_ok = True
                        return path
                    self._silero_ok = False
                    self._log("warning", "Silero unavailable, switching to edge-tts permanently")

                path = output_dir / f"line_{index:03d}.mp3"
                self._synthesize_edge(line.text, line.speaker, path)
                return path

            except AudioError:
                raise
            except Exception as e:  # noqa: BLE001
                self._log("warning", f"TTS line {index + 1} retry {attempt}/3: {e}")
                if attempt < len(_RETRY_BACKOFF):
                    time.sleep(delay)

        self._log("warning", f"TTS line {index + 1} skipped after 3 retries")
        return None

    def _synthesize_silero(self, text: str, voice: str, path: Path) -> bool:
        """
        Synthesize text via Silero TTS (local, torch.hub).
        Returns True on success, False if torch/silero is not available.
        """
        try:
            import sys  # noqa: PLC0415
            import torch  # noqa: PLC0415
        except ImportError:
            return False

        try:
            if self._silero_model is None:
                self._log("info", "Loading Silero TTS model (first run — downloading ~50 MB)...")
                # silero-models repo has its own src/ package (src/silero/).
                # Python's import cache (sys.modules) already holds OUR src/
                # package, so hubconf.py's `from src.silero import ...` finds
                # our src and fails. Temporarily evict our src from sys.modules
                # so torch.hub can import silero's src/ cleanly.
                evicted = {k: sys.modules.pop(k) for k in list(sys.modules)
                           if k == "src" or k.startswith("src.")}
                try:
                    self._silero_model, _ = torch.hub.load(
                        repo_or_dir="snakers4/silero-models",
                        model="silero_tts",
                        language="ru",
                        speaker="v4_ru",
                        verbose=False,
                    )
                finally:
                    # Restore our src package in the module cache.
                    sys.modules.update(evicted)
                self._log("info", "Silero TTS model loaded")

            self._silero_model.save_wav(
                text=text,
                speaker=voice,
                sample_rate=_SILERO_SAMPLE_RATE,
                put_accent=True,
                put_yo=True,
                audio_path=str(path),
            )
            return path.exists() and path.stat().st_size > 0

        except Exception as e:
            self._log("warning", f"Silero error: {e}")
            return False

    def _synthesize_edge(self, text: str, speaker: str, path: Path) -> None:
        """Synthesize via edge-tts using plain text + rate/pitch params."""
        import edge_tts  # noqa: PLC0415
        prosody = _EDGE_PROSODY.get(speaker, _EDGE_PROSODY["A"])
        communicate = edge_tts.Communicate(
            text,
            self._edge_voice,
            rate=prosody["rate"],
            pitch=prosody["pitch"],
        )
        asyncio.run(communicate.save(str(path)))
        if not path.exists() or path.stat().st_size == 0:
            raise AudioError("edge-tts returned empty audio")

    def _concat(self, paths: list[Path], output: Path) -> Path:
        """Concatenate WAV/MP3 segments using MoviePy."""
        from moviepy import AudioFileClip, concatenate_audioclips  # noqa: PLC0415
        clips = [AudioFileClip(str(p)) for p in paths]
        combined = concatenate_audioclips(clips)
        combined.write_audiofile(str(output), logger=None)
        for clip in clips:
            clip.close()
        combined.close()
        return output

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
