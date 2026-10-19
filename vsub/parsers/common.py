"""Shared subtitle parsing helpers."""

from __future__ import annotations

import html
import re

from ..models import Segment
from ..utils import guess_language, normalize_unicode

_SPEAKER_BRACKET_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?[\[【（(]\s*([^\]】）)]{1,24}?)\s*[\]】）)]\s*[:：]?\s*"
)
_SPEAKER_COLON_RE = re.compile(r"^\s*([\w\u4e00-\u9fff· .]{1,16})\s*[:：]\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_TIMESTAMP_TAG_RE = re.compile(r"<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}>")
_MULTI_SPACE_RE = re.compile(r"[ \t\u00a0\u3000]+")


def parse_srt_time(value: str) -> float:
    value = value.strip().replace(".", ",")
    m = re.match(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[,](\d{1,3})$", value)
    if not m:
        raise ValueError(f"非法 SRT 时间戳: {value!r}")
    h = int(m.group(1) or 0)
    minute, sec, ms = int(m.group(2)), int(m.group(3)), int(m.group(4).ljust(3, "0")[:3])
    return h * 3600 + minute * 60 + sec + ms / 1000.0


def parse_vtt_time(value: str) -> float:
    value = value.strip()
    m = re.match(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[.](\d{1,3})$", value)
    if not m:
        raise ValueError(f"非法 VTT 时间戳: {value!r}")
    h = int(m.group(1) or 0)
    minute, sec, ms = int(m.group(2)), int(m.group(3)), int(m.group(4).ljust(3, "0")[:3])
    return h * 3600 + minute * 60 + sec + ms / 1000.0


def parse_ass_time(value: str) -> float:
    value = value.strip()
    m = re.match(r"^(\d{1,3}):(\d{1,2}):(\d{1,2})[.](\d{1,2})$", value)
    if not m:
        raise ValueError(f"非法 ASS 时间戳: {value!r}")
    h, minute, sec, cs = (int(x) for x in m.groups())
    return h * 3600 + minute * 60 + sec + cs / 100.0


def strip_markup(text: str, *, ass: bool = False, html_tags: bool = True) -> str:
    text = _TIMESTAMP_TAG_RE.sub("", text)
    if ass:
        text = _ASS_TAG_RE.sub("", text)
        text = text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    if html_tags:
        text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\u00ad", "")
    return text


def clean_line(text: str) -> str:
    text = normalize_unicode(text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def normalize_cue_text(text: str) -> str:
    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    # Join wrapped lines, but keep an explicit two-line bilingual cue.
    return "\n".join(lines).strip()


def extract_speaker(text: str) -> tuple[str | None, str]:
    """Pull '[张三] ...' / '【张三】...' / '张三: ...' speaker prefixes."""
    m = _SPEAKER_BRACKET_RE.match(text)
    if m:
        name = m.group(1).strip()
        rest = text[m.end():].strip()
        if name and rest and not re.fullmatch(r"[\d:.\- ]+", name):
            return name, rest
    m = _SPEAKER_COLON_RE.match(text)
    if m:
        name = m.group(1).strip()
        rest = text[m.end():].strip()
        if name and rest and len(name) <= 16:
            return name, rest
    return None, text


def make_segment(
    start: float,
    end: float,
    text: str,
    *,
    speaker: str | None = None,
    lang: str | None = None,
    confidence: float | None = None,
    source: str | None = None,
) -> Segment | None:
    text = normalize_cue_text(text)
    if not text:
        return None
    auto_speaker, text = extract_speaker(text)
    if not text:
        return None
    if end < start:
        start, end = end, start
    return Segment(
        start=max(0.0, start),
        end=max(0.0, end),
        text=text,
        speaker=speaker or auto_speaker,
        lang=lang or guess_language(text),
        confidence=confidence,
        source=source,
    )


def sort_and_repair(segments: list[Segment]) -> list[Segment]:
    segments = sorted(segments, key=lambda s: (s.start, s.end))
    for i, seg in enumerate(segments):
        if seg.end < seg.start:
            seg.end = seg.start
        if i and seg.start < segments[i - 1].start:
            seg.start = segments[i - 1].start
    return segments
