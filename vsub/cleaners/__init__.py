"""Cleaning and paragraph segmentation."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from ..models import Paragraph, Segment, SubtitleTrack
from .bilingual import apply_inline_bilingual, make_bilingual
from .glossary import Glossary
from .text import (
    DEFAULT_DROP_PATTERNS,
    dedupe_segments,
    drop_noise,
    join_texts,
    merge_short_segments,
    normalize_text,
    restore_punctuation,
    split_inline_bilingual,
    split_long_segments,
)


@dataclass
class CleanOptions:
    merge_sentences: bool = True
    merge_gap: float = 0.9
    max_segment_chars: int = 140
    paragraph_gap: float = 1.8
    max_paragraph_chars: int = 280
    min_paragraph_chars: int = 60
    max_paragraph_duration: float = 30.0
    drop_ads: bool = True
    drop_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_DROP_PATTERNS))
    glossary: Glossary | None = None
    bilingual: bool = False
    primary_lang: str | None = None
    auto_punctuation: bool = True


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[。！？!?…]\s*$", text))


def group_paragraphs(segments: list[Segment], options: CleanOptions) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    current: list[Segment] = []

    def chars(items: list[Segment]) -> int:
        return len(join_texts(s.text for s in items))

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = join_texts(s.text for s in current)
        translation = join_texts(s.translation or "" for s in current) if any(s.translation for s in current) else None
        if text:
            paragraphs.append(
                Paragraph(
                    start=current[0].start,
                    end=max(s.end for s in current),
                    text=text,
                    translation=translation or None,
                    speaker=next((s.speaker for s in current if s.speaker), None),
                    segments=list(current),
                )
            )
        current = []

    for seg in segments:
        if current:
            prev = current[-1]
            gap = seg.start - prev.end
            same_speaker = seg.speaker == current[0].speaker or not seg.speaker
            too_long = chars(current) + len(seg.text) > options.max_paragraph_chars
            duration = seg.end - current[0].start
            should_break = (
                not same_speaker
                or gap >= options.paragraph_gap
                or gap >= 5.0
                or too_long
                or duration > options.max_paragraph_duration
                or (_ends_sentence(prev.text) and chars(current) >= options.min_paragraph_chars)
            )
            if should_break:
                flush()
        current.append(seg)
    flush()
    return paragraphs


def clean_track(
    track: SubtitleTrack,
    options: CleanOptions | None = None,
    *,
    secondary: SubtitleTrack | None = None,
) -> tuple[SubtitleTrack, list[Paragraph]]:
    options = options or CleanOptions()
    cleaned = copy.deepcopy(track)

    if options.bilingual:
        cleaned = make_bilingual(cleaned, secondary, primary_lang=options.primary_lang)

    prepared: list[Segment] = []
    for seg in cleaned.segments:
        text = normalize_text(seg.text)
        if options.glossary:
            text = options.glossary.apply(text)
        seg.text = text
        if options.bilingual and not seg.translation:
            inline_text, inline_translation = split_inline_bilingual(
                text, options.primary_lang or cleaned.language
            )
            if inline_translation:
                seg.text, seg.translation = inline_text, inline_translation
        if seg.speaker:
            seg.speaker = seg.speaker.strip()
        if seg.text.strip():
            prepared.append(seg)

    if options.drop_ads:
        prepared = drop_noise(prepared, options.drop_patterns)
    prepared = dedupe_segments(prepared)
    if options.merge_sentences:
        prepared = merge_short_segments(
            prepared,
            max_gap=options.merge_gap,
            max_chars=options.max_segment_chars,
        )
    # Whisper/OCR often returns 30-second blocks with no punctuation. Split
    # them after merging so the document keeps readable paragraphs/timestamps.
    prepared = split_long_segments(prepared, max_chars=options.max_segment_chars)
    if options.auto_punctuation and cleaned.source in {"asr", "ocr"}:
        prepared = [restore_punctuation(seg) for seg in prepared]
    prepared.sort(key=lambda s: (s.start, s.end))

    cleaned.segments = prepared
    if not cleaned.language and prepared:
        cleaned.language = prepared[0].lang
    cleaned.meta["segment_count_raw"] = len(track.segments)
    cleaned.meta["segment_count_clean"] = len(prepared)
    cleaned.meta["paragraph_count"] = 0

    paragraphs = group_paragraphs(prepared, options)
    cleaned.meta["paragraph_count"] = len(paragraphs)
    cleaned.meta["bilingual"] = bool(options.bilingual and any(p.translation for p in paragraphs))
    cleaned.meta["primary_language"] = cleaned.language
    if options.bilingual:
        if secondary:
            cleaned.meta["secondary_language"] = secondary.language
            cleaned.meta["secondary_source"] = secondary.source
        translated = sum(1 for p in paragraphs if p.translation)
        cleaned.meta["translation_coverage"] = round(
            translated / len(paragraphs), 3
        ) if paragraphs else 0.0
    return cleaned, paragraphs


__all__ = [
    "CleanOptions",
    "Glossary",
    "apply_inline_bilingual",
    "clean_track",
    "group_paragraphs",
    "make_bilingual",
]
