"""Shared data structures.

The intermediate representation is deliberately source-agnostic: external
SRT/ASS/VTT, Bilibili AI subtitles, embedded tracks, OCR and ASR all become a
``SubtitleTrack`` containing ``Segment`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    lang: str | None = None
    confidence: float | None = None
    translation: str | None = None
    source: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
        }
        if self.speaker:
            data["speaker"] = self.speaker
        if self.lang:
            data["lang"] = self.lang
        if self.confidence is not None:
            data["confidence"] = round(self.confidence, 4)
        if self.translation:
            data["translation"] = self.translation
        if self.source:
            data["source"] = self.source
        return data


@dataclass(slots=True)
class SubtitleTrack:
    source: str
    language: str | None
    segments: list[Segment]
    confidence: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max((s.end for s in self.segments), default=0.0)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "source": self.source,
            "language": self.language,
            "segments": [s.to_dict() for s in self.segments],
        }
        if self.confidence is not None:
            data["confidence"] = round(self.confidence, 4)
        if self.meta:
            data["meta"] = self.meta
        return data


@dataclass(slots=True)
class Paragraph:
    start: float
    end: float
    text: str
    translation: str | None = None
    speaker: str | None = None
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
        }
        if self.translation:
            data["translation"] = self.translation
        if self.speaker:
            data["speaker"] = self.speaker
        return data


@dataclass(slots=True)
class VideoPart:
    index: int
    title: str
    part_title: str | None = None
    bvid: str | None = None
    aid: int | None = None
    cid: int | None = None
    ep_id: int | None = None
    duration: float = 0.0
    url: str | None = None
    cover: str | None = None
    pubdate: str | None = None

    @property
    def display_title(self) -> str:
        if self.part_title and self.part_title.strip() and self.part_title != self.title:
            return f"{self.title} · {self.part_title}"
        return self.title

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "part_title": self.part_title,
            "bvid": self.bvid,
            "aid": self.aid,
            "cid": self.cid,
            "ep_id": self.ep_id,
            "duration": round(self.duration, 3),
            "url": self.url,
            "pubdate": self.pubdate,
        }


@dataclass(slots=True)
class VideoInfo:
    input: str
    platform: str
    title: str
    url: str | None = None
    owner: str | None = None
    owner_mid: int | None = None
    desc: str | None = None
    cover: str | None = None
    pubdate: str | None = None
    duration: float = 0.0
    bvid: str | None = None
    aid: int | None = None
    season_id: int | None = None
    parts: list[VideoPart] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "input": self.input,
            "platform": self.platform,
            "title": self.title,
            "url": self.url,
            "owner": self.owner,
            "owner_mid": self.owner_mid,
            "desc": self.desc,
            "cover": self.cover,
            "pubdate": self.pubdate,
            "duration": round(self.duration, 3),
            "bvid": self.bvid,
            "aid": self.aid,
            "season_id": self.season_id,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.extra:
            data["extra"] = self.extra
        return data


@dataclass(slots=True)
class PartResult:
    part: VideoPart
    track: SubtitleTrack
    paragraphs: list[Paragraph]
    quality: dict[str, Any]
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "part": self.part.to_dict(),
            "track": self.track.to_dict(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "quality": self.quality,
            "attempts": self.attempts,
        }


@dataclass(slots=True)
class VideoResult:
    video: VideoInfo
    parts: list[PartResult]
    outputs: dict[str, str] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "video": self.video.to_dict(),
            "parts": [p.to_dict() for p in self.parts],
            "outputs": self.outputs,
            "quality": self.quality,
        }
