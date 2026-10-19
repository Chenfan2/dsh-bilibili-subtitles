"""Turn URLs, files, directories and subtitle paths into pipeline items."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bilibili import parse_bilibili_link
from .errors import InputError, UnsupportedInputError
from .parsers import SUPPORTED_EXTENSIONS
from .utils import is_url

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".flv", ".avi", ".ts", ".m4v", ".wmv", ".mpg", ".mpeg"}


@dataclass(slots=True)
class InputItem:
    kind: str  # bilibili | video | subtitle
    raw: str
    video_path: Path | None = None
    subtitle_path: Path | None = None
    hint: str = ""


def _sibling_subtitle(video: Path) -> Path | None:
    for ext in (".srt", ".vtt", ".ass", ".ssa", ".json", ".txt"):
        candidate = video.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _subtitle_in_dir(directory: Path, hint: str) -> Path | None:
    if not directory.is_dir():
        return None
    hint_stem = Path(hint).stem.lower()
    candidates = [
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    for p in candidates:
        if p.stem.lower() == hint_stem:
            return p
    return directory  # let ExternalSubtitleProvider choose a stable default


def discover_inputs(
    inputs: list[str],
    *,
    subtitle: str | None = None,
) -> list[InputItem]:
    if not inputs:
        raise InputError("没有输入。请提供 Bilibili 链接、本地视频或字幕文件。")

    subtitle_path = Path(subtitle) if subtitle else None
    if subtitle_path and not subtitle_path.exists():
        raise InputError(f"外挂字幕不存在: {subtitle_path}")
    if subtitle_path and len(inputs) > 1 and subtitle_path.is_file():
        raise InputError("多个输入时，--subtitle 必须是目录，或分别处理。")

    items: list[InputItem] = []
    for raw in inputs:
        raw = raw.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if is_url(raw) or (not path.exists() and (raw.startswith("BV") or raw.lower().startswith("av"))):
            parse_bilibili_link(raw)
            sub = subtitle_path
            if sub and sub.is_dir():
                sub = _subtitle_in_dir(sub, raw)
            items.append(InputItem("bilibili", raw, subtitle_path=sub, hint=raw))
            continue
        if path.is_dir():
            videos = sorted(
                p for p in path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
            )
            sub_files = sorted(
                p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
            if not videos and not sub_files:
                raise UnsupportedInputError(
                    f"目录中没有视频或字幕文件: {path}",
                    hint=f"视频支持 {', '.join(sorted(VIDEO_EXTENSIONS))}；字幕支持 SRT/VTT/ASS/JSON/TXT。",
                )
            for video in videos:
                sub = subtitle_path or _sibling_subtitle(video)
                if sub and sub.is_dir():
                    sub = _subtitle_in_dir(sub, video.stem)
                items.append(
                    InputItem("video", str(video), video_path=video, subtitle_path=sub, hint=video.stem)
                )
            if not videos:
                for sub in sub_files:
                    items.append(InputItem("subtitle", str(sub), subtitle_path=sub, hint=sub.stem))
            continue

        if not path.exists():
            raise InputError(f"输入不存在: {path}")
        suffix = path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            sub = subtitle_path or _sibling_subtitle(path)
            if sub and sub.is_dir():
                sub = _subtitle_in_dir(sub, path.stem)
            items.append(
                InputItem("video", str(path), video_path=path, subtitle_path=sub, hint=path.stem)
            )
        elif suffix in SUPPORTED_EXTENSIONS:
            items.append(InputItem("subtitle", str(path), subtitle_path=path, hint=path.stem))
        else:
            raise UnsupportedInputError(
                f"不支持的文件类型: {path.suffix}",
                hint="支持视频、SRT/VTT/ASS/JSON/TXT 字幕，或 Bilibili 链接。",
            )
    if not items:
        raise InputError("没有可处理的输入。")
    return items
