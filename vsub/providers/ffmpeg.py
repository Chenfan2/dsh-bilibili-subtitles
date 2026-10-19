"""Locate ffmpeg/ffprobe without assuming they are on PATH."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _from_dir(directory: Path, name: str) -> Path | None:
    candidate = directory / _exe(name)
    if candidate.exists():
        return candidate
    return None


def find_ffmpeg(explicit: str | None = None) -> tuple[str | None, str | None]:
    """Return (ffmpeg, ffprobe) paths, or (None, None)."""
    if explicit:
        p = Path(explicit)
        if p.is_file():
            ffmpeg = p
            ffprobe = p.with_name(_exe("ffprobe"))
            return str(ffmpeg), str(ffprobe) if ffprobe.exists() else None
        if p.is_dir():
            ffmpeg = _from_dir(p, "ffmpeg")
            ffprobe = _from_dir(p, "ffprobe")
            if ffmpeg:
                return str(ffmpeg), str(ffprobe) if ffprobe else None

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg:
        return ffmpeg, ffprobe
    if ffprobe:
        candidate = Path(ffprobe).with_name(_exe("ffmpeg"))
        return (str(candidate) if candidate.exists() else None), ffprobe

    # Optional bundled binary from ``pip install imageio-ffmpeg``.
    try:
        import imageio_ffmpeg  # type: ignore

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg and Path(ffmpeg).exists():
            return ffmpeg, None
    except Exception:
        pass
    return None, None
