"""Bilingual subtitle alignment and inline 原文/译文 splitting."""

from __future__ import annotations

from ..models import Segment, SubtitleTrack
from ..utils import canonical_lang
from .text import join_texts, split_inline_bilingual


def _overlap(a: Segment, b: Segment) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def apply_inline_bilingual(track: SubtitleTrack, primary_lang: str | None = None) -> int:
    """Split cues that already contain two languages on separate lines."""
    changed = 0
    for seg in track.segments:
        if seg.translation:
            continue
        text, translation = split_inline_bilingual(seg.text, primary_lang or track.language)
        if translation:
            seg.text = text
            seg.translation = translation
            changed += 1
    return changed


def align_tracks(
    primary: SubtitleTrack,
    secondary: SubtitleTrack,
    *,
    max_gap: float = 1.5,
) -> SubtitleTrack:
    """Attach the secondary track's text to each primary segment by overlap.

    This is a timing alignment, not a translation-quality judgement.  It works
    for Bilibili dual subtitle tracks and for separately downloaded languages.
    """
    if not secondary.segments:
        return primary
    for seg in primary.segments:
        if seg.translation:
            continue
        overlaps = [other for other in secondary.segments if _overlap(seg, other) > 0.05]
        if overlaps:
            text = join_texts(other.text for other in overlaps)
        else:
            nearest = min(
                secondary.segments,
                key=lambda other: min(abs(other.start - seg.end), abs(seg.start - other.end)),
            )
            distance = min(abs(nearest.start - seg.end), abs(seg.start - nearest.end))
            text = nearest.text if distance <= max_gap else ""
        if text and text.strip() and text.strip() != seg.text.strip():
            seg.translation = text.strip()

    primary.meta["bilingual"] = True
    primary.meta["secondary_language"] = secondary.language
    primary.meta["secondary_source"] = secondary.source
    translated = sum(1 for s in primary.segments if s.translation)
    primary.meta["translation_coverage"] = round(
        translated / len(primary.segments), 3
    ) if primary.segments else 0.0
    return primary


def make_bilingual(
    primary: SubtitleTrack,
    secondary: SubtitleTrack | None,
    *,
    primary_lang: str | None = None,
) -> SubtitleTrack:
    if secondary and secondary.segments:
        align_tracks(primary, secondary)
    else:
        apply_inline_bilingual(primary, primary_lang)

    # If the primary track is English but the user asked for Chinese, try the
    # secondary as the main text and the primary as translation.
    if secondary and canonical_lang(primary.language) == "en" and canonical_lang(secondary.language) == "zh":
        primary, secondary = secondary, primary
        align_tracks(primary, secondary)
    return primary
