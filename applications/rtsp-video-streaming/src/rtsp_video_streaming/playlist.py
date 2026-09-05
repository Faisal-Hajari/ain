"""Discovery and ordering of the video files that make up the loop."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable, List, Sequence

DEFAULT_EXTENSIONS: Sequence[str] = (
    "mp4", "mkv", "mov", "avi", "webm", "m4v", "mpg", "mpeg", "ts", "flv", "wmv",
)


def normalize_extensions(extensions: Iterable[str]) -> List[str]:
    """Lowercase, strip a leading dot, and drop empties: ``.MP4`` -> ``mp4``."""
    out = []
    for ext in extensions:
        ext = ext.strip().lstrip(".").lower()
        if ext:
            out.append(ext)
    return out


class Playlist:
    """A directory of video files, rescanned at the start of every loop pass.

    Rescanning means files dropped into (or removed from) the folder while the
    server is running are picked up on the next pass without a restart.
    """

    def __init__(
        self,
        folder: Path,
        extensions: Iterable[str] = DEFAULT_EXTENSIONS,
        recursive: bool = False,
        shuffle: bool = False,
        seed: int | None = None,
    ) -> None:
        self.folder = Path(folder)
        self.extensions = set(normalize_extensions(extensions))
        self.recursive = recursive
        self.shuffle = shuffle
        self._random = random.Random(seed)

    def scan(self) -> List[Path]:
        """Return the files for one pass, sorted by path (or shuffled)."""
        if not self.folder.is_dir():
            return []
        pattern = "**/*" if self.recursive else "*"
        files = [
            p
            for p in self.folder.glob(pattern)
            if p.is_file() and p.suffix.lstrip(".").lower() in self.extensions
        ]
        files.sort(key=lambda p: str(p).lower())
        if self.shuffle:
            self._random.shuffle(files)
        return files
