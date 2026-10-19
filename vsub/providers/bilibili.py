"""Bilibili platform/AI subtitle provider."""

from __future__ import annotations

from typing import Iterable

from ..bilibili import BilibiliClient
from ..models import SubtitleTrack, VideoPart
from .base import SubtitleProvider


class BilibiliSubtitleProvider(SubtitleProvider):
    name = "bilibili"

    def __init__(
        self,
        client: BilibiliClient,
        *,
        languages: Iterable[str] | None = None,
        bilingual: bool = False,
    ):
        self.client = client
        self.languages = list(languages or [])
        self.bilingual = bilingual

    def fetch_tracks(self, part: VideoPart) -> list[SubtitleTrack]:
        return self.client.fetch_subtitle_tracks(
            part,
            languages=self.languages,
            bilingual=self.bilingual,
        )

    def fetch(self, part: VideoPart) -> SubtitleTrack:
        tracks = self.fetch_tracks(part)
        return tracks[0]
