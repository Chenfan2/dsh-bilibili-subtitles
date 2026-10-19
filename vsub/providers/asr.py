"""Optional ASR fallback using faster-whisper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..errors import ASRError, DependencyMissingError
from ..models import Segment, SubtitleTrack
from ..utils import canonical_lang, exp_confidence
from .base import SubtitleProvider


def _patch_av_open() -> None:
    """faster-whisper passes ``metadata_errors`` that PyAV 19 removed."""
    try:
        import av

        current = av.open
        if getattr(current, "_vsub_compatible", False):
            return

        def open_compatible(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return current(*args, **kwargs)

        open_compatible._vsub_compatible = True  # type: ignore[attr-defined]
        av.open = open_compatible  # type: ignore[assignment]
    except Exception:
        pass


class ASRSubtitleProvider(SubtitleProvider):
    name = "asr"

    def __init__(
        self,
        *,
        model_size: str = "small",
        language: str | None = None,
        device: str = "auto",
        compute_type: str | None = None,
        model_dir: str | Path | None = None,
        initial_prompt: str | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.model_size = model_size
        self.language = canonical_lang(language) if language else None
        self.device = device
        self.compute_type = compute_type
        env_dir = os.environ.get("VSUB_MODEL_DIR")
        self.model_dir = Path(model_dir or env_dir or Path.cwd() / ".vsub-models-cache")
        self.initial_prompt = initial_prompt
        self.log = logger or (lambda _msg: None)

    def available(self) -> tuple[bool, str]:
        try:
            _patch_av_open()
            import faster_whisper  # noqa: F401
            return True, ""
        except Exception:
            return False, (
                "未安装 faster-whisper。安装后可启用语音转写兜底：\n"
                "  python -m pip install faster-whisper"
            )

    def _resolve_device(self) -> tuple[str, str]:
        device = self.device
        if device == "auto":
            device = "cpu"
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() > 0:
                    device = "cuda"
            except Exception:
                pass
        compute = self.compute_type
        if not compute:
            compute = "float16" if device == "cuda" else "int8"
        return device, compute

    def fetch(self, media_path: str | Path) -> SubtitleTrack:
        ok, message = self.available()
        if not ok:
            raise DependencyMissingError(message)
        try:
            _patch_av_open()
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - environment dependent
            raise DependencyMissingError(f"faster-whisper 导入失败: {exc}") from exc

        media_path = Path(media_path)
        if not media_path.exists():
            raise ASRError(f"音频/视频文件不存在: {media_path}")

        device, compute_type = self._resolve_device()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.log(
            f"加载 Whisper 模型 {self.model_size}（device={device}, compute_type={compute_type}）..."
        )
        try:
            model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute_type,
                download_root=str(self.model_dir),
            )
        except Exception as exc:  # noqa: BLE001
            if device == "cuda":
                self.log(f"CUDA 加载失败，改用 CPU: {exc}")
                device, compute_type = "cpu", "int8"
                try:
                    model = WhisperModel(
                        self.model_size,
                        device=device,
                        compute_type=compute_type,
                        download_root=str(self.model_dir),
                    )
                except Exception as cpu_exc:  # noqa: BLE001
                    raise ASRError(
                        f"Whisper 模型加载失败: {cpu_exc}",
                        hint=(
                            "首次运行需要联网下载模型（small 约 460MB）。"
                            "可改用 --asr-model base/tiny，或设置 --model-dir 到可写目录。"
                        ),
                    ) from cpu_exc
            else:
                raise ASRError(
                    f"Whisper 模型加载失败: {exc}",
                    hint=(
                        "首次运行需要联网下载模型（small 约 460MB）。"
                        "可改用 --asr-model base/tiny，或设置 --model-dir 到可写目录。"
                    ),
                ) from exc

        self.log("开始语音转写（首次运行需要下载模型，可能较慢）...")
        try:
            prompt = self.initial_prompt
            style = {
                "zh": "以下是普通话视频的转写，请使用简体中文并添加标点。",
                "en": "This is English speech; transcribe it with punctuation.",
                "ja": "以下は日本語の音声です。句読点を付けて文字起こししてください。",
            }.get(self.language or "")
            if style:
                prompt = f"{style}\n{prompt}" if prompt else style

            segments_iter, info = model.transcribe(
                str(media_path),
                language=self.language,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=prompt,
                word_timestamps=False,
            )
            segments: list[Segment] = []
            total_duration = float(getattr(info, "duration", 0.0) or 0.0)
            for i, item in enumerate(segments_iter, start=1):
                text = (item.text or "").strip()
                if not text:
                    continue
                no_speech = float(getattr(item, "no_speech_prob", 0.0) or 0.0)
                if no_speech > 0.85 and len(text) < 6:
                    continue
                confidence = exp_confidence(getattr(item, "avg_logprob", None))
                segments.append(
                    Segment(
                        start=float(item.start),
                        end=float(item.end),
                        text=text,
                        confidence=confidence,
                        source=self.name,
                        lang=canonical_lang(getattr(info, "language", None)),
                    )
                )
                if i % 25 == 0:
                    self.log(f"  已转写 {i} 段，进度约 {item.end:.0f}s / {total_duration:.0f}s")
        except Exception as exc:  # noqa: BLE001
            raise ASRError(
                f"语音转写失败: {exc}",
                hint="检查音频文件是否完整；如为视频，可先用 ffmpeg 提取音频。",
            ) from exc

        if not segments:
            raise ASRError("语音转写没有产生任何文本（可能全程静音或音频损坏）。")
        avg_conf = sum(s.confidence for s in segments if s.confidence is not None)
        conf_count = sum(1 for s in segments if s.confidence is not None)
        track = SubtitleTrack(
            source=self.name,
            language=canonical_lang(getattr(info, "language", None)) or self.language,
            segments=segments,
            confidence=(avg_conf / conf_count) if conf_count else None,
            meta={
                "model": self.model_size,
                "device": device,
                "compute_type": compute_type,
                "language_probability": round(
                    float(getattr(info, "language_probability", 0.0) or 0.0), 4
                ),
                "audio_duration": round(total_duration, 2),
                "media_file": str(media_path),
            },
        )
        self.log(f"语音转写完成: {len(segments)} 段")
        return track
