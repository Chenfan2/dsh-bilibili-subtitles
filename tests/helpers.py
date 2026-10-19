from __future__ import annotations

import shutil
from pathlib import Path

from vsub.cleaners import CleanOptions, clean_track
from vsub.models import PartResult, SubtitleTrack, VideoInfo, VideoPart
from vsub.quality import analyze
from vsub.renderers import RenderContext
from vsub.utils import now_local_iso

ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / "_tmp"


def workspace_dir(name: str) -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / name
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_context(track: SubtitleTrack, *, title: str = "测试视频", duration: float = 30.0):
    cleaned, paragraphs = clean_track(track, CleanOptions())
    quality = analyze(cleaned, paragraphs, video_duration=duration, expected_language=track.language)
    video = VideoInfo(
        input=title,
        platform="local",
        title=title,
        duration=duration,
        parts=[VideoPart(index=1, title=title, duration=duration)],
    )
    part = PartResult(
        part=video.parts[0],
        track=cleaned,
        paragraphs=paragraphs,
        quality=quality,
        attempts=[{"provider": track.source, "status": "ok"}],
    )
    context = RenderContext(
        video=video,
        parts=[part],
        quality=quality,
        generated_at=now_local_iso(),
    )
    return context
