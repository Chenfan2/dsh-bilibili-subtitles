"""Small utilities shared by providers, cleaners and renderers."""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def format_timestamp(seconds: float, style: str = "clock") -> str:
    """Format seconds as clock / SRT / VTT / ASS timecode."""
    seconds = max(0.0, float(seconds or 0.0))
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)

    if style == "srt":
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    if style == "vtt":
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    if style == "ass":
        cs = int(round(ms / 10))
        if cs >= 100:
            s, cs = s + 1, cs - 100
        return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def human_duration(seconds: float | None) -> str:
    if not seconds:
        return "未知"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分 {s} 秒"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"


# ---------------------------------------------------------------------------
# Text / language helpers
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_JA_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    cjk = sum(1 for c in letters if _CJK_RE.match(c) or _JA_KANA_RE.match(c) or _HANGUL_RE.match(c))
    return cjk / len(letters)


def guess_language(text: str) -> str:
    """Very small heuristic used for cleanup warnings, not for translation."""
    if not text.strip():
        return "unknown"
    if _HANGUL_RE.search(text):
        return "ko"
    if _JA_KANA_RE.search(text):
        return "ja"
    if _CJK_RE.search(text):
        return "zh"
    if _LATIN_RE.search(text):
        return "en"
    return "unknown"


_LANG_ALIASES = {
    "zh": "zh",
    "chi": "zh",
    "zho": "zh",
    "cmn": "zh",
    "yue": "zh",
    "en": "en",
    "eng": "en",
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "ko": "ko",
    "kor": "ko",
    "fr": "fr",
    "fre": "fr",
    "fra": "fr",
    "de": "de",
    "ger": "de",
    "deu": "de",
    "es": "es",
    "spa": "es",
    "ru": "ru",
    "rus": "ru",
}


def canonical_lang(lang: str | None) -> str | None:
    if not lang:
        return None
    low = lang.strip().lower().replace("_", "-")
    if low in {"", "und", "unknown", "default", "none", "zxx"}:
        return None
    if low.startswith("ai-"):
        low = low[3:]
    base = low.split("-")[0]
    if base in _LANG_ALIASES:
        return _LANG_ALIASES[base]
    # Keep unusual language tags (e.g. sign language codes) but never infer
    # from an arbitrary word prefix such as "default".
    return base


LANGUAGE_LABELS = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
    "unknown": "未知",
}


def language_label(lang: str | None) -> str:
    base = canonical_lang(lang)
    if not base:
        return "未知"
    return LANGUAGE_LABELS.get(base, lang or base)


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def normalize_unicode(text: str) -> str:
    """NFC only; NFKC would destroy Chinese full-width punctuation."""
    return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_text_auto(path: str | Path) -> str:
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def safe_filename(name: str, max_len: int = 80, fallback: str = "video") -> str:
    name = normalize_unicode(name or "")
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name


def json_dumps(data: object, pretty: bool = True) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None)


def now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def timestamp_to_date(ts: int | float | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


def redact_url(url: str | None) -> str | None:
    """Never print signed CDN URLs (they contain access tokens)."""
    if not url:
        return None
    try:
        p = urlparse(url)
        path = p.path
        if len(path) > 70:
            path = path[:40] + "..." + path[-20:]
        return f"{p.scheme}://{p.hostname or ''}{path}"
    except Exception:
        return "<url>"


def redact_cookie(value: str | None) -> str:
    if not value:
        return "<none>"
    return f"<{len(value)} chars>"


def parse_page_selection(spec: str | None, total: int) -> list[int]:
    """Parse '1,3-5' (1-based) into zero-based indices."""
    if not spec or spec.strip().lower() in {"auto", "default"}:
        return [0]
    if spec.strip().lower() == "all":
        return list(range(total))
    result: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            for n in range(start, end + 1):
                if 1 <= n <= total and (n - 1) not in result:
                    result.append(n - 1)
        else:
            try:
                n = int(chunk)
            except ValueError:
                continue
            if 1 <= n <= total and (n - 1) not in result:
                result.append(n - 1)
    return result or [0]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def is_url(text: str) -> bool:
    return bool(re.match(r"^(https?://|www\.)", text.strip(), re.I))


def host_matches(host: str, domain: str) -> bool:
    host = (host or "").lower().split(":")[0]
    return host == domain or host.endswith("." + domain)


def format_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return "0 B"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def exp_confidence(avg_logprob: float | None) -> float | None:
    if avg_logprob is None:
        return None
    try:
        return clamp(math.exp(float(avg_logprob)), 0.0, 1.0)
    except (ValueError, OverflowError):
        return None
