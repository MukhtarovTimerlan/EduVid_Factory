from pathlib import Path

from src.utils.exceptions import VideoCompositionError

_FPS = 30
# Landscape (16:9) and portrait (9:16) output dimensions
_LANDSCAPE = (1920, 1080)
_PORTRAIT = (1080, 1920)
# Character height as fraction of output height
_CHAR_HEIGHT_FRAC = 0.30


class VideoComposer:
    """Assembles final MP4: background image/video + two character photos + audio.

    Output orientation is detected automatically from the background asset:
    - Portrait background  → 1080×1920, characters in opposite corners
    - Landscape background → 1920×1080, characters at bottom-left / bottom-right
    """

    def __init__(self, logger=None) -> None:
        self._logger = logger

    def assemble(
        self,
        background: Path,
        char_a: Path,
        char_b: Path,
        audio: Path,
        output_path: Path,
    ) -> Path:
        """
        Compose video layers and write MP4.
        Returns path to the output file.
        Raises VideoCompositionError on failure.
        """
        self._log("info", "Video composition started")
        try:
            return self._compose(background, char_a, char_b, audio, output_path)
        except VideoCompositionError:
            raise
        except Exception as e:
            raise VideoCompositionError(f"MoviePy composition failed: {e}") from e

    # ── private ───────────────────────────────────────────────────────────────

    def _compose(
        self,
        background: Path,
        char_a: Path,
        char_b: Path,
        audio: Path,
        output_path: Path,
    ) -> Path:
        from moviepy import (  # noqa: PLC0415
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
        )
        import moviepy.video.fx as vfx  # noqa: PLC0415

        audio_clip = AudioFileClip(str(audio))
        duration = audio_clip.duration

        # ── Background: load and detect orientation ───────────────────────────
        bg_suffix = background.suffix.lower()
        if bg_suffix in (".mp4", ".mov", ".avi"):
            raw_bg = VideoFileClip(str(background)).without_audio()
            if raw_bg.duration < duration:
                raw_bg = vfx.Loop(duration=duration).apply(raw_bg)
            else:
                raw_bg = raw_bg.subclipped(0, duration)
        else:
            raw_bg = ImageClip(str(background)).with_duration(duration)

        bg_w, bg_h = raw_bg.size
        portrait = bg_h > bg_w
        out_w, out_h = _PORTRAIT if portrait else _LANDSCAPE
        char_h = int(out_h * _CHAR_HEIGHT_FRAC)

        self._log("info", f"Orientation={'portrait' if portrait else 'landscape'} | output={out_w}×{out_h}")

        bg_clip = raw_bg.resized((out_w, out_h))

        # ── Characters: opposite corners (portrait) or bottom sides (landscape) ─
        if portrait:
            # Char A: top-left corner, Char B: bottom-right corner
            char_a_clip = (
                ImageClip(str(char_a))
                .with_duration(duration)
                .resized(height=char_h)
                .with_position(("left", "top"))
            )
            char_b_clip = (
                ImageClip(str(char_b))
                .with_duration(duration)
                .resized(height=char_h)
                .with_position(("right", "bottom"))
            )
        else:
            # Char A: bottom-left, Char B: bottom-right
            char_a_clip = (
                ImageClip(str(char_a))
                .with_duration(duration)
                .resized(height=char_h)
                .with_position(("left", "bottom"))
            )
            char_b_clip = (
                ImageClip(str(char_b))
                .with_duration(duration)
                .resized(height=char_h)
                .with_position(("right", "bottom"))
            )

        final = CompositeVideoClip(
            [bg_clip, char_a_clip, char_b_clip],
            size=(out_w, out_h),
        ).with_audio(audio_clip)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_video(final, output_path)

        audio_clip.close()
        bg_clip.close()
        char_a_clip.close()
        char_b_clip.close()
        final.close()

        size_bytes = output_path.stat().st_size
        self._log(
            "info",
            f"Video composition done | size={size_bytes} duration={duration:.1f}s "
            f"resolution={out_w}×{out_h}",
        )
        return output_path

    def _write_video(self, clip, output_path: Path) -> None:
        """Try libx264 first, fall back to h264 on codec mismatch."""
        try:
            clip.write_videofile(
                str(output_path),
                fps=_FPS,
                codec="libx264",
                audio_codec="aac",
                audio_fps=44100,
                logger=None,
            )
        except Exception as e:
            if "libx264" in str(e) or "codec" in str(e).lower():
                self._log("warning", "libx264 failed, retrying with h264")
                clip.write_videofile(
                    str(output_path),
                    fps=_FPS,
                    codec="h264",
                    audio_codec="aac",
                    audio_fps=44100,
                    logger=None,
                )
            else:
                raise VideoCompositionError(str(e)) from e

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
