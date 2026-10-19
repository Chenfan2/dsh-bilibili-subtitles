"""SRT parser tolerant of missing cue numbers / blank lines and BOM."""

from __future__ import annotations

import re

from ..models import Segment, SubtitleTrack
from ..utils import guess_language
from .common import make_segment, parse_srt_time, sort_and_repair, strip_markup

_TIME_LINE = re.compile(
    r"(?P<start>\d{1,3}:\d{1,2}:\d{1,2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,3}:\d{1,2}:\d{1,2}[,.]\d{1,3})(?P<settings>[^\r\n]*)"
)


def parse_srt_text(text: str, *, source: str = "external", language: str | None = None) -> SubtitleTrack:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(_TIME_LINE.finditer(text))
    segments: list[Segment] = []
    for i, match in enumerate(matches):
        start = parse_srt_time(match.group("start"))
        end = parse_srt_time(match.group("end"))
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        # Remove a trailing/leading numeric cue index.
        lines = body.splitlines()
        if lines and re.fullmatch(r"\s*\d+\s*", lines[0]):
            lines = lines[1:]
        if lines and re.fullmatch(r"\s*\d+\s*", lines[-1]) and i + 1 < len(matches):
            lines = lines[:-1]
        body = strip_markup("\n".join(lines), ass=True, html_tags=True)
        seg = make_segment(start, end, body, source=source, lang=language)
        if seg:
            segments.append(seg)
    segments = sort_and_repair(segments)
    lang = language or (segments[0].lang if segments else None)
    return SubtitleTrack(source=source, language=lang, segments=segments)
