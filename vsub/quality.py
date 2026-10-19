"""Automatic quality checks and the JSON quality report."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from .models import Paragraph, SubtitleTrack
from .utils import cjk_ratio, format_timestamp, now_local_iso


def _merged_intervals(track: SubtitleTrack, duration: float) -> list[tuple[float, float]]:
    intervals = []
    for seg in track.segments:
        start = max(0.0, min(seg.start, duration or seg.end))
        end = max(start, min(seg.end, duration or seg.end))
        if end > start:
            intervals.append((start, end))
    intervals.sort()
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def compute_coverage(track: SubtitleTrack, duration: float) -> tuple[float, list[tuple[float, float]]]:
    intervals = _merged_intervals(track, duration)
    covered = sum(end - start for start, end in intervals)
    if duration <= 0:
        return 0.0, intervals
    return min(1.0, covered / duration), intervals


def _is_duplicate_text(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE).lower()

    na, nb = norm(a), norm(b)
    return bool(na) and na == nb


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = 0
    for ch in text:
        if ch == "\ufffd":
            bad += 1
        elif unicodedata.category(ch) in {"Cc", "Cs", "Co", "Cn"} and ch not in "\n\t":
            bad += 1
    return bad / len(text)


def analyze(
    track: SubtitleTrack,
    paragraphs: list[Paragraph],
    *,
    video_duration: float = 0.0,
    expected_language: str | None = None,
    extra_warnings: Iterable[str] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = list(extra_warnings or [])
    segments = track.segments
    duration = max(float(video_duration or 0.0), max((s.end for s in segments), default=0.0))
    coverage, intervals = compute_coverage(track, duration)
    span_start = min((s.start for s in segments), default=0.0)
    span_end = max((s.end for s in segments), default=0.0)
    span_duration = max(0.0, span_end - span_start)
    covered_seconds = sum(end - start for start, end in intervals)
    span_coverage = min(1.0, covered_seconds / span_duration) if span_duration else 0.0
    chars = sum(len(s.text) for s in segments)
    paragraphs_chars = sum(len(p.text) for p in paragraphs)

    overlaps = 0
    negative = 0
    empty = 0
    duplicates = 0
    low_confidence = 0
    speech_anomalies = 0
    garbled = 0
    prev = None
    for seg in segments:
        if seg.end < seg.start:
            negative += 1
        if not seg.text.strip():
            empty += 1
        if prev is not None and seg.start < prev.end - 0.05:
            overlaps += 1
        if prev is not None and _is_duplicate_text(prev.text, seg.text):
            duplicates += 1
        if seg.confidence is not None and seg.confidence < 0.6:
            low_confidence += 1
        seg_duration = max(0.001, seg.end - seg.start)
        cps = len(seg.text) / seg_duration
        if (cps > 15 and len(seg.text) >= 8) or (cps < 0.5 and seg_duration > 4 and len(seg.text) < 4):
            speech_anomalies += 1
        garbled += sum(1 for ch in seg.text if ch == "\ufffd")
        prev = seg

    if not segments:
        warnings.append("没有解析到任何字幕片段。")
    if coverage < 0.9 and segments and (
        span_coverage < 0.9 or (duration and span_duration < 0.7 * duration)
    ):
        warnings.append(
            f"字幕时间覆盖率仅 {coverage:.1%}（目标 ≥90%；内容区间 {span_coverage:.1%}）。"
        )
    if overlaps:
        warnings.append(f"发现 {overlaps} 处时间戳重叠。")
    if negative:
        warnings.append(f"发现 {negative} 处结束时间早于开始时间。")
    if duplicates:
        warnings.append(f"发现 {duplicates} 处相邻重复文本。")
    if low_confidence:
        warnings.append(f"发现 {low_confidence} 段低置信度字幕（<0.6）。")
    if speech_anomalies:
        warnings.append(f"发现 {speech_anomalies} 段语速异常（可能断句/时间轴问题）。")
    if garbled:
        warnings.append(f"文本中有 {garbled} 个替换字符（乱码风险）。")
    if chars:
        ratio = _garbled_ratio("".join(s.text for s in segments))
        if ratio > 0.002:
            warnings.append(f"乱码字符占比 {ratio:.2%}。")

    track_lang = track.language
    cjk = cjk_ratio("".join(s.text for s in segments)) if chars else 0.0
    if expected_language:
        expected = expected_language.lower()
        if expected.startswith("zh") and cjk < 0.2 and chars > 40:
            warnings.append("期望中文字幕，但文本中中文占比很低，请检查语言选择。")
        if expected.startswith("en") and cjk > 0.8 and chars > 40:
            warnings.append("期望英文字幕，但文本中中文占比很高，请检查语言选择。")
    if not track_lang and segments:
        track_lang = segments[0].lang

    bilingual = bool(track.meta.get("bilingual"))
    translation_coverage = track.meta.get("translation_coverage")
    if bilingual:
        if not translation_coverage:
            translated = sum(1 for p in paragraphs if p.translation)
            translation_coverage = round(translated / len(paragraphs), 3) if paragraphs else 0.0
        if translation_coverage < 0.7:
            warnings.append(f"双语对齐覆盖率仅 {translation_coverage:.1%}。")

    gaps = []
    for (_, end), (start, _) in zip(intervals, intervals[1:]):
        if start - end >= 10:
            gaps.append((end, start, start - end))
    if gaps:
        longest = max(gaps, key=lambda g: g[2])
        warnings.append(
            f"有 {len(gaps)} 段超过 10 秒的空白，最长 {longest[2]:.0f} 秒"
            f"（{format_timestamp(longest[0])}–{format_timestamp(longest[1])}）。"
        )

    status = "ok"
    # Do not fail a video merely because it contains long music/silence; fail
    # when the subtitle only covers a small slice of the actual timeline.
    if not segments or (coverage < 0.3 and span_duration < 0.3 * max(duration, 1.0)):
        status = "fail"
    elif warnings:
        status = "warn"

    score = 100.0
    score -= max(0.0, 0.95 - coverage) * 45
    score -= min(25, overlaps * 1.5)
    score -= min(10, negative * 5)
    score -= min(10, duplicates * 0.5)
    score -= min(10, low_confidence * 1.0)
    score -= min(10, len(warnings) * 1.5)
    score = round(max(0.0, min(100.0, score)), 1)

    def sample(items: list[Paragraph]) -> list[dict]:
        return [
            {
                "start": format_timestamp(p.start),
                "text": p.text[:120],
            }
            for p in items[:5]
        ]

    mid = len(paragraphs) // 2
    samples = {
        "head": sample(paragraphs[:5]),
        "middle": sample(paragraphs[max(0, mid - 2): mid + 3]),
        "tail": sample(paragraphs[-5:]),
    }

    return {
        "status": status,
        "score": score,
        "source": track.source,
        "language": track_lang,
        "bilingual": bilingual,
        "translation_coverage": translation_coverage,
        "segments": len(segments),
        "paragraphs": len(paragraphs),
        "chars": chars,
        "paragraph_chars": paragraphs_chars,
        "duration": round(duration, 2),
        "duration_covered": round(coverage, 4),
        "coverage_ratio": round(coverage, 4),
        "coverage_span": round(span_coverage, 4),
        "content_span": round(span_duration, 2),
        "gaps_over_10s": len(gaps),
        "longest_gap": round(max((g[2] for g in gaps), default=0.0), 1),
        "overlaps": overlaps,
        "negative_durations": negative,
        "empty_segments": empty,
        "duplicate_segments": duplicates,
        "low_confidence_segments": low_confidence,
        "speech_rate_anomalies": speech_anomalies,
        "garbled_chars": garbled,
        "cjk_ratio": round(cjk, 3),
        "warnings": warnings,
        "errors": [] if segments else ["NO_SEGMENTS"],
        "samples": samples,
        "generated_at": now_local_iso(),
    }


def aggregate(part_reports: list[dict[str, Any]], *, duration: float = 0.0) -> dict[str, Any]:
    if not part_reports:
        return {
            "status": "fail",
            "score": 0.0,
            "parts": 0,
            "warnings": ["没有成功处理的视频分P。"],
            "errors": ["NO_PARTS"],
        }
    total_segments = sum(int(r.get("segments") or 0) for r in part_reports)
    total_paragraphs = sum(int(r.get("paragraphs") or 0) for r in part_reports)
    total_chars = sum(int(r.get("chars") or 0) for r in part_reports)
    total_duration = sum(float(r.get("duration") or 0) for r in part_reports)
    covered = sum(float(r.get("duration_covered") or 0) * float(r.get("duration") or 0) for r in part_reports)
    coverage = covered / total_duration if total_duration else 0.0
    warnings = []
    for i, report in enumerate(part_reports, start=1):
        for warning in report.get("warnings") or []:
            warnings.append(f"P{i}: {warning}")
    statuses = [r.get("status") for r in part_reports]
    status = "fail" if any(s == "fail" for s in statuses) else ("warn" if any(s == "warn" for s in statuses) else "ok")
    score = round(sum(float(r.get("score") or 0) for r in part_reports) / len(part_reports), 1)
    return {
        "status": status,
        "score": score,
        "parts": len(part_reports),
        "segments": total_segments,
        "paragraphs": total_paragraphs,
        "chars": total_chars,
        "duration": round(total_duration or duration, 2),
        "duration_covered": round(coverage, 4),
        "coverage_ratio": round(coverage, 4),
        "warnings": warnings,
        "errors": [],
        "part_status": statuses,
        "generated_at": now_local_iso(),
    }
