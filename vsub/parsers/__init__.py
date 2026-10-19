"""Subtitle format parsers."""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import ParseError
from ..models import SubtitleTrack
from ..utils import read_text_auto
from .ass import parse_ass_text
from .bilibili_json import parse_bilibili_json
from .plain import parse_plain_text
from .srt import parse_srt_text
from .vtt import parse_vtt_text

SUPPORTED_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".json", ".txt"}


def parse_subtitle_text(
    text: str,
    *,
    source: str = "external",
    language: str | None = None,
    hint: str | None = None,
) -> SubtitleTrack:
    stripped = text.lstrip("\ufeff \t\r\n")
    hint = (hint or "").lower()
    if hint in {".ass", ".ssa"} or "[events]" in stripped[:2000].lower():
        return parse_ass_text(text, source=source, language=language)
    if hint == ".vtt" or stripped.startswith("WEBVTT"):
        return parse_vtt_text(text, source=source, language=language)
    if hint == ".json" or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ParseError(f"JSON 字幕解析失败: {exc}") from exc
        if isinstance(data, list):
            data = {"body": data}
        return parse_bilibili_json(data, source=source, language=language)
    if hint == ".txt":
        return parse_plain_text(text, source=source, language=language)
    # Default: timestamp arrows mean SRT.
    return parse_srt_text(text, source=source, language=language)


def parse_subtitle_file(
    path: str | Path,
    *,
    source: str = "external",
    language: str | None = None,
) -> SubtitleTrack:
    p = Path(path)
    if not p.exists():
        raise ParseError(f"字幕文件不存在: {p}")
    text = read_text_auto(p)
    suffix = p.suffix.lower()
    try:
        track = parse_subtitle_text(text, source=source, language=language, hint=suffix)
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"解析字幕文件失败: {p} ({exc})") from exc
    if not track.segments:
        raise ParseError(
            f"字幕文件没有可用片段: {p}",
            hint="检查文件是否为有效的 SRT/VTT/ASS/Bilibili JSON。",
        )
    track.meta.setdefault("file", str(p))
    return track


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "parse_ass_text",
    "parse_bilibili_json",
    "parse_plain_text",
    "parse_srt_text",
    "parse_subtitle_file",
    "parse_subtitle_text",
    "parse_vtt_text",
]
