"""Embedded subtitle track provider (ffprobe + ffmpeg)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import DependencyMissingError, NoSubtitleError, ProviderError
from ..models import SubtitleTrack
from ..parsers import parse_subtitle_file
from ..utils import canonical_lang
from .base import SubtitleProvider
from .ffmpeg import find_ffmpeg

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(slots=True)
class EmbeddedStream:
    ordinal: int  # index among subtitle streams, for -map 0:s:N
    global_index: int
    codec: str
    language: str | None = None
    title: str | None = None


def _run(cmd: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )


class EmbeddedSubtitleProvider(SubtitleProvider):
    name = "embedded"

    def __init__(
        self,
        video_path: str | Path,
        *,
        ffmpeg: str | None = None,
        language: str | None = None,
        workdir: str | Path | None = None,
    ):
        self.video_path = Path(video_path)
        self.ffmpeg, self.ffprobe = find_ffmpeg(ffmpeg)
        self.language = language
        self.workdir = Path(workdir) if workdir else None

    def available(self) -> tuple[bool, str]:
        if not self.video_path.exists():
            return False, f"视频不存在: {self.video_path}"
        if not self.ffmpeg:
            return False, "未找到 ffmpeg，无法读取内嵌字幕。"
        return True, ""

    def _from_ffmpeg_stderr(self) -> list[EmbeddedStream]:
        if not self.ffmpeg:
            return []
        proc = _run([self.ffmpeg, "-hide_banner", "-i", str(self.video_path)], timeout=60)
        streams: list[EmbeddedStream] = []
        pattern = re.compile(
            r"Stream #0:(\d+)(?:\[[^\]]+\])?(?:\([^)]*\))?: Subtitle:\s*([^\s,]+)(.*)"
        )
        for line in (proc.stderr or "").splitlines():
            m = pattern.search(line)
            if not m:
                continue
            global_index = int(m.group(1))
            codec = m.group(2)
            rest = m.group(3)
            lang = None
            title = None
            lm = re.search(r"\(([a-zA-Z-]{2,})\)", rest)
            if lm:
                candidate = lm.group(1).lower()
                if candidate not in {"und", "default", "unknown", "none"}:
                    lang = candidate
            tm = re.search(r"title\s*:\s*([^,]+)", rest, re.I)
            if tm:
                title = tm.group(1).strip()
            streams.append(
                EmbeddedStream(len(streams), global_index, codec, lang, title)
            )
        return streams

    def streams(self) -> list[EmbeddedStream]:
        if not self.ffprobe:
            return self._from_ffmpeg_stderr()
        proc = _run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(self.video_path),
            ],
            timeout=90,
        )
        if proc.returncode != 0:
            return self._from_ffmpeg_stderr()
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return self._from_ffmpeg_stderr()
        streams: list[EmbeddedStream] = []
        for stream in data.get("streams") or []:
            if stream.get("codec_type") != "subtitle":
                continue
            tags = stream.get("tags") or {}
            language = tags.get("language")
            if language and str(language).lower() in {"und", "default", "unknown", "none"}:
                language = None
            streams.append(
                EmbeddedStream(
                    ordinal=len(streams),
                    global_index=int(stream.get("index") or 0),
                    codec=str(stream.get("codec_name") or "unknown"),
                    language=language,
                    title=tags.get("title"),
                )
            )
        return streams

    def _choose(self, streams: list[EmbeddedStream]) -> EmbeddedStream:
        if not streams:
            raise NoSubtitleError(
                "视频没有内嵌字幕轨。",
                hint="可提供外挂字幕（--subtitle）或启用 --asr。",
            )
        if self.language:
            want = canonical_lang(self.language)
            for stream in streams:
                if canonical_lang(stream.language) == want:
                    return stream
        return streams[0]

    def fetch(self) -> SubtitleTrack:
        ok, message = self.available()
        if not ok:
            raise DependencyMissingError(message, hint="安装 ffmpeg 后重试，或用 --ffmpeg 指定路径。")
        streams = self.streams()
        stream = self._choose(streams)
        workdir = Path(self.workdir) if self.workdir else Path(tempfile.mkdtemp(prefix="vsub_embedded_"))
        workdir.mkdir(parents=True, exist_ok=True)
        out = workdir / f"embedded_{stream.ordinal}.srt"
        cmd = [
            self.ffmpeg or "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(self.video_path),
            "-map",
            f"0:s:{stream.ordinal}",
            "-c:s",
            "srt",
            str(out),
        ]
        proc = _run(cmd, timeout=300)
        if proc.returncode != 0 or not out.exists():
            raise ProviderError(
                f"内嵌字幕提取失败（{stream.codec}）: {(proc.stderr or '').strip()[:300]}",
                hint="位图字幕（PGS/VobSub）无法直接转 SRT，请改用 OCR 或外挂字幕。",
            )
        track = parse_subtitle_file(out, source=self.name, language=stream.language or self.language)
        track.meta.update(
            {
                "stream_ordinal": stream.ordinal,
                "stream_index": stream.global_index,
                "codec": stream.codec,
                "stream_title": stream.title,
                "file": str(self.video_path),
            }
        )
        return track
