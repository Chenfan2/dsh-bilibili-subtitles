"""Provider interface and shared provider helpers."""

from __future__ import annotations

from ..models import SubtitleTrack


class SubtitleProvider:
    """Every subtitle source returns the same intermediate track."""

    name = "base"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def fetch(self, *args, **kwargs) -> SubtitleTrack:  # pragma: no cover - interface
        raise NotImplementedError
