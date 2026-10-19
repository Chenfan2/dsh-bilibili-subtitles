"""Experimental hard-coded subtitle OCR (ffmpeg frames + RapidOCR).

This adapter is intentionally conservative: it only runs on local video files,
uses a bottom-area crop by default, and deduplicates consecutive frames.  It is
not used for Bilibili URLs unless a video file has been downloaded separately.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ..errors import DependencyMissingError, OCRError, ProviderError
from ..models import Segment, SubtitleTrack
from ..utils import canonical_lang, guess_language, similarity
from .base import SubtitleProvider
from .ffmpeg import find_ffmpeg

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class OCRSubtitleProvider(SubtitleProvider):
    name = "ocr"

    def __init__(
        self,
        video_path: str | Path,
        *,
        ffmpeg: str | None = None,
        language: str | None = None,
        fps: float = 2.0,
        crop_ratio: float = 0.30,
        full_frame: bool = False,
        min_confidence: float = 0.5,
        workdir: str | Path | None = None,
        keep_frames: bool = False,
        logger: Callable[[str], None] | None = None,
    ):
        self.video_path = Path(video_path)
        self.ffmpeg, _ = find_ffmpeg(ffmpeg)
        self.language = canonical_lang(language) if language else None
        self.fps = max(0.2, float(fps))
        self.crop_ratio = min(0.9, max(0.05, float(crop_ratio)))
        self.full_frame = full_frame
        self.min_confidence = min_confidence
        self.workdir = Path(workdir) if workdir else None
        self.keep_frames = keep_frames
        self.log = logger or (lambda _msg: None)

    def available(self) -> tuple[bool, str]:
        if not self.video_path.exists():
            return False, f"视频不存在: {self.video_path}"
        if not self.ffmpeg:
            return False, "未找到 ffmpeg，无法抽取视频帧。"
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:
            return False, (
                "未安装 RapidOCR。安装后可启用硬字幕 OCR：\n"
                "  python -m pip install rapidocr_onnxruntime"
            )
        return True, ""

    def _extract_frames(self) -> tuple[Path, int]:
        tmp = Path(self.workdir) if self.workdir else Path(tempfile.mkdtemp(prefix="vsub_ocr_"))
        frames = tmp / "frames"
        if frames.exists():
            shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir(parents=True, exist_ok=True)
        vf = f"fps={self.fps}"
        if not self.full_frame:
            vf += f",crop=iw:ih*{self.crop_ratio:.3f}:0:ih*{1 - self.crop_ratio:.3f}"
        cmd = [
            self.ffmpeg or "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(self.video_path),
            "-vf",
            vf,
            "-q:v",
            "2",
            str(frames / "frame_%06d.jpg"),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise OCRError(f"抽帧失败: {(proc.stderr or '').strip()[:300]}")
        count = len(list(frames.glob("frame_*.jpg")))
        if not count:
            raise OCRError("没有抽取到任何视频帧。")
        return frames, count

    def _ocr_frame(self, engine, path: Path) -> tuple[str, float]:
        result, _ = engine(str(path))
        if not result:
            return "", 0.0
        items = []
        for item in result:
            if len(item) < 3:
                continue
            box, text, score = item[0], str(item[1]).strip(), float(item[2])
            if not text or score < self.min_confidence:
                continue
            try:
                y = min(point[1] for point in box)
                x = min(point[0] for point in box)
            except Exception:
                y, x = 0, 0
            items.append((y, x, text, score))
        items.sort(key=lambda it: (round(it[0] / 20), it[1]))
        text = " ".join(it[2] for it in items).strip()
        confidence = sum(it[3] for it in items) / len(items) if items else 0.0
        return text, confidence

    def fetch(self) -> SubtitleTrack:
        ok, message = self.available()
        if not ok:
            raise DependencyMissingError(message)
        from rapidocr_onnxruntime import RapidOCR

        self.log(f"抽取视频帧（fps={self.fps}, crop={self.crop_ratio:.0%}）...")
        frames, count = self._extract_frames()
        self.log(f"开始 OCR：{count} 帧")
        engine = RapidOCR()

        segments: list[Segment] = []
        current_text = ""
        current_start = 0.0
        current_end = 0.0
        current_conf: list[float] = []
        last_seen = -999.0

        def flush() -> None:
            nonlocal current_text, current_start, current_end, current_conf
            if current_text and current_end > current_start:
                segments.append(
                    Segment(
                        start=current_start,
                        end=current_end,
                        text=current_text,
                        confidence=(sum(current_conf) / len(current_conf)) if current_conf else None,
                        source=self.name,
                        lang=self.language or guess_language(current_text),
                    )
                )
            current_text = ""
            current_conf = []

        for idx, frame in enumerate(sorted(frames.glob("frame_*.jpg")), start=1):
            t = (idx - 1) / self.fps
            text, conf = self._ocr_frame(engine, frame)
            if not text:
                if current_text and t - last_seen > max(1.5, 2.5 / self.fps):
                    flush()
                continue
            if current_text and similarity(text, current_text) >= 0.86:
                current_end = t + 1.0 / self.fps
                last_seen = t
                if len(text) > len(current_text) + 3:
                    current_text = text
                current_conf.append(conf)
            else:
                flush()
                current_text = text
                current_start = t
                current_end = t + 1.0 / self.fps
                current_conf = [conf]
                last_seen = t
            if idx % 100 == 0:
                self.log(f"  OCR 进度 {idx}/{count}")
        flush()

        if not self.keep_frames:
            shutil.rmtree(frames, ignore_errors=True)
        if not segments:
            raise OCRError(
                "OCR 没有识别到字幕文本。",
                hint="尝试 --ocr-full-frame，或调整 --ocr-crop（默认底部 30%）。",
            )
        avg_conf = sum(s.confidence for s in segments if s.confidence is not None)
        conf_count = sum(1 for s in segments if s.confidence is not None)
        return SubtitleTrack(
            source=self.name,
            language=self.language or (segments[0].lang if segments else None),
            segments=segments,
            confidence=(avg_conf / conf_count) if conf_count else None,
            meta={
                "fps": self.fps,
                "crop_ratio": 1.0 if self.full_frame else self.crop_ratio,
                "full_frame": self.full_frame,
                "frames": count,
                "video": str(self.video_path),
            },
        )
