"""Parser for Bilibili AI/CC subtitle JSON.

Typical payload::

    {"body": [{"from": 0.0, "to": 2.34, "location": 2, "text": "..."}]}
"""

from __future__ import annotations

import json
from typing import Any

from ..models import Segment, SubtitleTrack
from .common import make_segment, sort_and_repair


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_bilibili_json(
    data: dict | str,
    *,
    language: str | None = None,
    source: str = "bilibili",
    meta: dict | None = None,
) -> SubtitleTrack:
    if isinstance(data, str):
        data = json.loads(data)
    body = data.get("body")
    if body is None:
        # Some exports use "subtitles"/"segments" or a bare list.
        body = data.get("subtitles") or data.get("segments") or data.get("data") or []
    if isinstance(body, dict):
        body = body.get("body") or body.get("subtitles") or []
    if not isinstance(body, list):
        body = []

    segments: list[Segment] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        start = _as_float(item.get("from", item.get("start", item.get("start_time", 0))))
        end = _as_float(item.get("to", item.get("end", item.get("end_time", 0))))
        text = item.get("text", item.get("content", "")) or ""
        if not text:
            continue
        seg = make_segment(start, end, str(text), source=source, lang=language)
        if seg:
            segments.append(seg)

    segments = sort_and_repair(segments)
    track_meta = {"format": "bilibili-json"}
    if meta:
        track_meta.update(meta)
    lang = language or (segments[0].lang if segments else None)
    return SubtitleTrack(source=source, language=lang, segments=segments, meta=track_meta)
