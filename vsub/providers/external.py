"""User-supplied subtitle file provider (highest priority)."""

from __future__ import annotations

from pathlib import Path

from ..errors import ParseError
from ..models import SubtitleTrack
from ..parsers import SUPPORTED_EXTENSIONS, parse_subtitle_file
from .base import SubtitleProvider


def _pick_in_directory(directory: Path, hint: str | None) -> Path:
    candidates = [
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not candidates:
        raise ParseError(
            f"目录中没有字幕文件: {directory}",
            hint=f"支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}。",
        )
    if hint:
        stem = Path(hint).stem.lower()
        for p in candidates:
            if p.stem.lower() == stem:
                return p
        for p in candidates:
            if stem and (stem in p.stem.lower() or p.stem.lower() in stem):
                return p
    # Stable choice: SRT > VTT > ASS > JSON > TXT, then name.
    order = {".srt": 0, ".vtt": 1, ".ass": 2, ".ssa": 2, ".json": 3, ".txt": 4}
    candidates.sort(key=lambda p: (order.get(p.suffix.lower(), 9), p.name.lower()))
    return candidates[0]


class ExternalSubtitleProvider(SubtitleProvider):
    name = "external"

    def __init__(self, path: str | Path, *, language: str | None = None, hint: str | None = None):
        self.path = Path(path)
        self.language = language
        self.hint = hint

    def available(self) -> tuple[bool, str]:
        return self.path.exists(), f"外挂字幕不存在: {self.path}"

    def fetch(self) -> SubtitleTrack:
        path = self.path
        if path.is_dir():
            path = _pick_in_directory(path, self.hint)
        if not path.exists():
            raise ParseError(f"外挂字幕不存在: {path}")
        track = parse_subtitle_file(path, source=self.name, language=self.language)
        track.source = self.name
        track.meta["file"] = str(path)
        return track
