import os
import random
from pathlib import Path

from src.utils.exceptions import AssetsMissingError

_BG_EXTS = {".mp4", ".mov", ".jpg", ".jpeg", ".png"}
_CHAR_EXTS = {".jpg", ".jpeg", ".png"}


class AssetSelector:
    """Randomly picks background and character assets from local directories."""

    def __init__(self, logger=None) -> None:
        assets_dir = Path(os.environ.get("ASSETS_DIR", "assets"))
        self._bg_dir = assets_dir / "backgrounds"
        self._char_dir = assets_dir / "characters"
        self._logger = logger

    def pick(self) -> tuple[Path, Path, Path]:
        """
        Return (background_path, char_a_path, char_b_path).
        Raises AssetsMissingError if required files are absent.
        """
        backgrounds = [p for p in self._bg_dir.iterdir() if p.suffix.lower() in _BG_EXTS]
        characters = [p for p in self._char_dir.iterdir() if p.suffix.lower() in _CHAR_EXTS]

        if not backgrounds:
            raise AssetsMissingError(
                f"No background assets found in {self._bg_dir}. "
                "Add at least one .mp4, .mov, .jpg, or .png file."
            )
        if not characters:
            raise AssetsMissingError(
                f"No character assets found in {self._char_dir}. "
                "Add at least one .jpg or .png file."
            )

        bg = random.choice(backgrounds)

        if len(characters) >= 2:
            char_a, char_b = random.sample(characters, 2)
        else:
            char_a = char_b = characters[0]

        if self._logger:
            self._logger.info(
                f"Assets selected | bg={bg.name} char_a={char_a.name} char_b={char_b.name}"
            )

        return bg, char_a, char_b
