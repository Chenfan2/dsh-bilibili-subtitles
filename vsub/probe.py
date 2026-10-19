"""Local media probing (ffprobe) with a filename-only fallback."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .providers.ffmpeg import find_ffmpeg

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(slots=True)
class MediaProbe:
    title: str
    duration: float = 0.0
    owner: str | None = None
    has_subtitle_stream: bool = False
    width: int | None = None
    height: int | None = None


def probe_media(path: str | Path, ffmpeg: str | None = None) -> MediaProbe:
    p = Path(path)
    title = p.stem
    ffmpeg_exe, ffprobe = find_ffmpeg(ffmpeg)
    if not ffprobe:
        # imageio-ffmpeg only ships ffmpeg. Parse its banner for duration and
        # subtitle streams instead of giving up on local metadata.
        if ffmpeg_exe:
            try:
                proc = subprocess.run(
                    [ffmpeg_exe, "-hide_banner", "-i", str(p)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    creationflags=_CREATE_NO_WINDOW,
                )
                stderr = proc.stderr or ""
                dm = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
                duration = 0.0
                if dm:
                    duration = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
                return MediaProbe(
                    title=title,
                    duration=duration,
                    has_subtitle_stream=bool(re.search(r"Stream #\d+:\d+.*: Subtitle:", stderr)),
                )
            except Exception:
                pass
        return MediaProbe(title=title)
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            return MediaProbe(title=title)
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return MediaProbe(title=title)

    fmt = data.get("format") or {}
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    title = tags.get("title") or title
    owner = tags.get("artist") or tags.get("album_artist") or None
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    streams = data.get("streams") or []
    has_sub = any(s.get("codec_type") == "subtitle" for s in streams)
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    width = int(video_stream["width"]) if video_stream and video_stream.get("width") else None
    height = int(video_stream["height"]) if video_stream and video_stream.get("height") else None
    return MediaProbe(
        title=str(title),
        duration=duration,
        owner=owner,
        has_subtitle_stream=has_sub,
        width=width,
        height=height,
    )
