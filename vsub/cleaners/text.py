"""Text normalisation, deduplication and advertisement/watermark removal."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from ..models import Segment
from ..utils import cjk_ratio, normalize_unicode, similarity

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")
_SPACE_RE = re.compile(r"[ \t\u00a0\u3000]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)

# Default noise patterns. They only apply to short cues so real content that
# happens to mention "关注" is not removed.
DEFAULT_DROP_PATTERNS = [
    r"^(记得)?(点赞|投币|收藏|转发|分享|订阅|关注|一键三连)"
    r"(?:\s*[、,，和与/]\s*(点赞|投币|收藏|转发|分享|订阅|关注|一键三连))*"
    r"(?:支持)?(?:一下|一波)?[!！。.,，\s]*$",
    r"^关注.{0,12}(公众号|UP主|主播|频道)",
    r"^字幕(由|制作|提供|组)",
    r"^(本视频|视频来源|更多精彩|下载.{0,10}客户端)",
    r"^(谢谢观看|感谢观看|我们下期再见|下期再见|Thanks for watching|Subtitles by|Amara\.org)",
    r"^请不吝点赞.{0,30}(订阅|转发|打赏)",
    r"^(如果|要是).{0,12}(有帮助|喜欢).{0,24}(点赞|三连)",
    r"^(如果|要是)(这期|本期)?视频对(你|大家)有帮助[，,]?$",
    r"^[\[【(（]?\s*广告\s*[\]】)）]?$",
]


def normalize_text(text: str) -> str:
    text = normalize_unicode(text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text).strip()


def is_noise(text: str, patterns: Iterable[str] = DEFAULT_DROP_PATTERNS) -> bool:
    clean = text.strip()
    if not clean:
        return True
    if len(clean) <= 60:
        for pattern in patterns:
            if re.search(pattern, clean, re.I):
                return True
    return False


def split_inline_bilingual(text: str, primary_lang: str | None = None) -> tuple[str, str | None]:
    """Split '原文\\n译文' or '原文 / 译文' cues into text + translation.

    Only splits when the two sides use different scripts; karaoke-style double
    Chinese lines are kept as one cue.
    """
    text = text.strip()
    if not text:
        return text, None
    candidates = [line.strip() for line in text.splitlines() if line.strip()]
    if len(candidates) < 2 and " / " in text:
        candidates = [part.strip() for part in text.split(" / ", 1) if part.strip()]
    if len(candidates) < 2:
        return text, None

    def latin_ratio(value: str) -> float:
        letters = [c for c in value if not c.isspace()]
        if not letters:
            return 0.0
        return sum(1 for c in letters if c.isascii() and c.isalpha()) / len(letters)

    cjk_line = max(candidates, key=cjk_ratio)
    latin_line = max(candidates, key=latin_ratio)
    if cjk_line == latin_line:
        return " ".join(candidates), None
    if cjk_ratio(cjk_line) < 0.15 or latin_ratio(latin_line) < 0.35:
        return " ".join(candidates), None

    if primary_lang == "en":
        primary, translation = latin_line, cjk_line
    else:
        primary, translation = cjk_line, latin_line
    return primary, translation


def dedupe_segments(
    segments: list[Segment],
    *,
    window: float = 2.5,
    threshold: float = 0.92,
) -> list[Segment]:
    result: list[Segment] = []
    for seg in segments:
        key = re.sub(r"[\s\W_]+", "", seg.text, flags=re.UNICODE).lower()
        if not key:
            continue
        drop = False
        for prev in reversed(result[-4:]):
            if seg.start - prev.end > window:
                break
            prev_key = re.sub(r"[\s\W_]+", "", prev.text, flags=re.UNICODE).lower()
            if key == prev_key:
                drop = True
                break
            if len(key) <= 30 and (key in prev_key or prev_key in key) and similarity(key, prev_key) >= threshold:
                drop = True
                break
        if not drop:
            result.append(seg)
    return result


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[。！？!?…；;]\s*$", text))


def _starts_new_sentence(text: str) -> bool:
    return bool(re.match(r"^[A-Z\u4e00-\u9fff]", text))


def join_texts(parts: Iterable[str]) -> str:
    result = ""
    for raw in parts:
        part = raw.strip()
        if not part:
            continue
        if not result:
            result = part
            continue
        prev = result[-1]
        nxt = part[0]
        if re.match(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]", nxt) or re.match(
            r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]", prev
        ):
            sep = ""
        elif prev in ".!?;:" and nxt.isascii() and (nxt.isalnum() or nxt in "\"'"):
            sep = " "
        elif prev in ",;:" and nxt.isascii() and nxt.isalnum():
            sep = " "
        elif prev in "，。！？、；：,.!?;:）)]】":
            sep = ""
        elif prev.isalnum() and nxt.isalnum():
            sep = " "
        else:
            sep = ""
        if result.endswith(sep) and sep:
            result += part
        elif result.endswith((" ", "\n")):
            result += part
        else:
            result += sep + part
    return result.strip()


def merge_short_segments(
    segments: list[Segment],
    *,
    max_gap: float = 0.9,
    max_chars: int = 140,
    max_duration: float = 16.0,
) -> list[Segment]:
    """Join cues cut mid-sentence, respecting punctuation, gaps and speakers."""
    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: (s.start, s.end))
    # Trim pathological overlaps from the previous cue (keeping both texts).
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        if cur.start < prev.end - 0.05 and (prev.speaker is None or prev.speaker == cur.speaker):
            prev.end = max(prev.start + 0.05, cur.start)

    merged: list[Segment] = [ordered[0]]
    for cur in ordered[1:]:
        prev = merged[-1]
        gap = cur.start - prev.end
        combined_len = len(prev.text) + len(cur.text)
        combined_dur = cur.end - prev.start
        same_speaker = prev.speaker == cur.speaker
        can_merge = (
            same_speaker
            and gap <= max_gap
            and combined_len <= max_chars
            and combined_dur <= max_duration
            and not _ends_sentence(prev.text)
        )
        # Very short cues are almost always fragments.
        if (
            same_speaker
            and gap <= max_gap + 0.8
            and len(prev.text) <= 12
            and not _ends_sentence(prev.text)
            and combined_len <= max_chars
        ):
            can_merge = True
        if can_merge:
            prev.text = join_texts([prev.text, cur.text])
            prev.end = max(prev.end, cur.end)
            if cur.translation:
                prev.translation = join_texts([prev.translation or "", cur.translation])
            if prev.confidence is not None and cur.confidence is not None:
                prev.confidence = min(prev.confidence, cur.confidence)
            elif cur.confidence is not None and prev.confidence is None:
                prev.confidence = cur.confidence
        else:
            merged.append(cur)
    return merged


def _split_text(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = -1
        for punct in "。！？；!?;，,、 ":
            idx = window.rfind(punct)
            if idx >= max_chars // 2:
                cut = max(cut, idx + 1)
        if cut <= 0:
            cut = max_chars
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _split_by_ratios(text: str, ratios: list[float]) -> list[str]:
    text = text.strip()
    if not text or len(ratios) <= 1:
        return [text] if text else []
    total = sum(ratios) or 1.0
    chunks: list[str] = []
    consumed = 0
    for i, ratio in enumerate(ratios):
        if i == len(ratios) - 1:
            chunks.append(text[consumed:].strip())
            break
        target = consumed + max(1, round(len(text) * ratio / total))
        target = min(len(text), target)
        cut = target
        for punct in "。！？；!?;，,、 ":
            idx = text.rfind(punct, consumed, min(len(text), target + 8))
            if idx >= consumed:
                cut = max(cut, idx + 1)
        cut = min(len(text), max(consumed + 1, cut))
        chunks.append(text[consumed:cut].strip())
        consumed = cut
    return [c for c in chunks if c]


def split_long_segments(segments: list[Segment], *, max_chars: int = 140) -> list[Segment]:
    """Split punctuation-less ASR/OCR blocks into readable timestamped chunks."""
    result: list[Segment] = []
    for seg in segments:
        text = seg.text.strip()
        if len(text) <= max_chars:
            result.append(seg)
            continue
        chunks = _split_text(text, max_chars)
        if len(chunks) <= 1:
            result.append(seg)
            continue
        ratios = [len(c) for c in chunks]
        translations = _split_by_ratios(seg.translation or "", ratios) if seg.translation else []
        cursor = seg.start
        span = max(0.0, seg.end - seg.start)
        total_chars = sum(ratios) or 1
        for i, chunk in enumerate(chunks):
            ratio = len(chunk) / total_chars
            end = seg.end if i == len(chunks) - 1 else cursor + span * ratio
            result.append(
                Segment(
                    start=cursor,
                    end=max(cursor, end),
                    text=chunk,
                    speaker=seg.speaker,
                    lang=seg.lang,
                    confidence=seg.confidence,
                    translation=translations[i] if i < len(translations) else None,
                    source=seg.source,
                )
            )
            cursor = end
    return result


def restore_punctuation(segment: Segment) -> Segment:
    """Add a conservative terminal full stop to ASR/OCR cues.

    Inserting punctuation inside a cue requires word/clause knowledge; naive
    discourse-marker rules produce errors such as ``我。可是``.  We only close
    the cue at its known segment boundary, which is safe and still makes long
    ASR blocks much easier to read.
    """
    text = segment.text.strip()
    if not text or re.search(r"[。！？!?…]\s*$", text):
        return segment
    text = re.sub(r"[，,、；;：:]\s*$", "", text)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= max(4, len(text) * 0.3):
        if len(text) >= 6:
            text += "。"
    elif len(text) >= 12:
        text += "."
    segment.text = text
    return segment


def drop_noise(segments: list[Segment], patterns: Iterable[str] = DEFAULT_DROP_PATTERNS) -> list[Segment]:
    result: list[Segment] = []
    for seg in segments:
        text = strip_urls(seg.text)
        if not text:
            continue
        if is_noise(text, patterns):
            continue
        seg.text = text
        result.append(seg)
    return result
