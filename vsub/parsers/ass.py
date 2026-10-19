"""ASS/SSA parser: Format line driven, handles override tags and \\N."""

from __future__ import annotations

import re

from ..models import Segment, SubtitleTrack
from .common import make_segment, parse_ass_time, sort_and_repair, strip_markup

_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")
_FORMAT_RE = re.compile(r"^Format:\s*(.+)$", re.I)
_DIALOGUE_RE = re.compile(r"^(Dialogue|Comment):\s*(.*)$", re.I)


def parse_ass_text(text: str, *, source: str = "external", language: str | None = None) -> SubtitleTrack:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    in_events = False
    fields: list[str] = []
    segments: list[Segment] = []
    meta: dict = {"format": "ass"}
    for line in text.splitlines():
        section = _SECTION_RE.match(line)
        if section:
            in_events = section.group(1).strip().lower() == "events"
            continue
        if not in_events:
            continue
        fmt = _FORMAT_RE.match(line)
        if fmt:
            fields = [f.strip().lower() for f in fmt.group(1).split(",")]
            continue
        dlg = _DIALOGUE_RE.match(line)
        if not dlg or dlg.group(1).lower() == "comment" or not fields:
            continue
        payload = dlg.group(2)
        parts = payload.split(",", len(fields) - 1)
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        try:
            start = parse_ass_time(row.get("start", ""))
            end = parse_ass_time(row.get("end", ""))
        except ValueError:
            continue
        raw = row.get("text", "")
        speaker = (row.get("name") or "").strip()
        if speaker.lower() in {"default", "narrator"}:
            speaker = None
        body = strip_markup(raw, ass=True, html_tags=True)
        seg = make_segment(start, end, body, source=source, lang=language, speaker=speaker)
        if seg:
            segments.append(seg)
    segments = sort_and_repair(segments)
    lang = language or (segments[0].lang if segments else None)
    return SubtitleTrack(source=source, language=lang, segments=segments, meta=meta)
