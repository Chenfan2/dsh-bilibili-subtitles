"""Plain-text fallback: '[00:12] text' or one paragraph per line."""

from __future__ import annotations

import re

from ..models import Segment, SubtitleTrack
from .common import make_segment, sort_and_repair

_TS_RE = re.compile(r"^\s*[\[(]?(\d{1,3}):(\d{2})(?::(\d{2}))?[\])]?\s*[-–—:]?\s*(.*)$")
_LINE_TIME_RE = re.compile(
    r"^\s*\[?(\d{1,3}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,3}))?\]?\s*(.*)$"
)


def parse_plain_text(text: str, *, source: str = "external", language: str | None = None) -> SubtitleTrack:
    segments: list[Segment] = []
    cursor = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_TIME_RE.match(line)
        if m:
            a, b, c, ms, body = m.groups()
            if c is not None:
                sec = int(a) * 3600 + int(b) * 60 + int(c)
            else:
                sec = int(a) * 60 + int(b)
            if ms:
                sec += int(ms.ljust(3, "0")[:3]) / 1000.0
            body = body.strip()
            if body:
                seg = make_segment(sec, sec + 3.0, body, source=source, lang=language)
                if seg:
                    segments.append(seg)
                cursor = sec + 3.0
            continue
        seg = make_segment(cursor, cursor + 2.5, line, source=source, lang=language)
        if seg:
            segments.append(seg)
        cursor += 2.5
    segments = sort_and_repair(segments)
    return SubtitleTrack(source=source, language=language, segments=segments)
