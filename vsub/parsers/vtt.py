"""WebVTT parser (speaker tags, cue settings, NOTE/STYLE blocks)."""

from __future__ import annotations

import re

from ..models import Segment, SubtitleTrack
from .common import make_segment, parse_vtt_time, sort_and_repair, strip_markup

_TIME_LINE = re.compile(
    r"^(?P<start>\d{1,3}:\d{1,2}:\d{1,2}[.]\d{1,3}|\d{1,2}:\d{1,2}[.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,3}:\d{1,2}:\d{1,2}[.]\d{1,3}|\d{1,2}:\d{1,2}[.]\d{1,3})(?P<settings>.*)$",
    re.M,
)
_VOICE_RE = re.compile(r"<v(?:\.[^ >]+)?\s+([^>]+)>")
_TAG_RE = re.compile(r"</?[^>]+>")


def _parse_blocks(text: str, source: str, language: str | None) -> list[Segment]:
    segments: list[Segment] = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0].strip().upper()
        if first.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "X-TIMESTAMP-MAP")):
            # A WEBVTT header block can still contain cues after the header line.
            if not first.startswith("WEBVTT"):
                continue
            lines = lines[1:]
            if not lines:
                continue
        time_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_idx is None:
            continue
        match = _TIME_LINE.search(lines[time_idx])
        if not match:
            continue
        start = parse_vtt_time(match.group("start"))
        end = parse_vtt_time(match.group("end"))
        body_lines = lines[time_idx + 1:]
        body = "\n".join(body_lines)
        voice = _VOICE_RE.search(body)
        speaker = voice.group(1).strip() if voice else None
        body = _TAG_RE.sub("", body)
        body = strip_markup(body, html_tags=True)
        seg = make_segment(
            start, end, body, source=source, lang=language, speaker=speaker
        )
        if seg:
            segments.append(seg)
    return segments


def _parse_regex(text: str, source: str, language: str | None) -> list[Segment]:
    matches = list(_TIME_LINE.finditer(text))
    segments: list[Segment] = []
    for i, match in enumerate(matches):
        start = parse_vtt_time(match.group("start"))
        end = parse_vtt_time(match.group("end"))
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        lines = body.splitlines()
        # Drop the next cue's optional identifier.
        if lines and lines[0].strip() and i + 1 < len(matches) and i > 0:
            pass
        voice = _VOICE_RE.search(body)
        speaker = voice.group(1).strip() if voice else None
        body = _TAG_RE.sub("", body)
        body = strip_markup(body, html_tags=True)
        seg = make_segment(start, end, body, source=source, lang=language, speaker=speaker)
        if seg:
            segments.append(seg)
    return segments


def parse_vtt_text(text: str, *, source: str = "external", language: str | None = None) -> SubtitleTrack:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    header_lang = None
    m = re.search(r"^Language:\s*(\S+)", text[:500], re.M | re.I)
    if m:
        header_lang = m.group(1)
    segments = _parse_blocks(text, source, language or header_lang)
    if not segments:
        segments = _parse_regex(text, source, language or header_lang)
    segments = sort_and_repair(segments)
    lang = language or header_lang or (segments[0].lang if segments else None)
    return SubtitleTrack(source=source, language=lang, segments=segments, meta={"format": "vtt"})
