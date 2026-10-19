"""Typed errors for the video-subtitle-to-doc pipeline.

Every error carries a stable machine-readable ``code`` and a suggested next
step (``hint``).  The CLI maps ``exit_code`` to the process exit status so an
agent can decide whether retrying with another subtitle source makes sense.
"""

from __future__ import annotations


class VSubError(Exception):
    code = "VSUB_ERROR"
    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None, detail: object | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
        }

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        text = self.message
        if self.hint:
            text += f"\n提示: {self.hint}"
        return text


class InputError(VSubError):
    code = "INPUT_ERROR"
    exit_code = 2


class UnsupportedInputError(InputError):
    code = "UNSUPPORTED_INPUT"


class BilibiliError(VSubError):
    code = "BILIBILI_API_ERROR"
    exit_code = 2


class LoginRequiredError(BilibiliError):
    code = "LOGIN_REQUIRED"
    exit_code = 3

    def __init__(self, message: str = "该视频的字幕需要登录后才能读取。", *, hint: str | None = None):
        super().__init__(
            message,
            hint=hint
            or "设置 BILIBILI_SESSDATA 环境变量，或使用 --sessdata/--cookies 提供 B 站 Cookie；"
            "也可以加 --asr 用语音转写兜底（需安装 faster-whisper）。",
        )


class NoSubtitleError(VSubError):
    code = "NO_SUBTITLE"
    exit_code = 3

    def __init__(
        self,
        message: str = "没有找到可用字幕。",
        *,
        hint: str | None = None,
        detail: object | None = None,
    ):
        super().__init__(
            message,
            hint=hint or "可用 --subtitle 提供外挂字幕，或加 --asr 使用语音转写。",
            detail=detail,
        )


class ParseError(VSubError):
    code = "PARSE_ERROR"
    exit_code = 2


class DependencyMissingError(VSubError):
    code = "DEPENDENCY_MISSING"
    exit_code = 4


class ProviderError(VSubError):
    code = "PROVIDER_ERROR"
    exit_code = 3


class ASRError(ProviderError):
    code = "ASR_FAILED"


class OCRError(ProviderError):
    code = "OCR_FAILED"


class RenderError(VSubError):
    code = "RENDER_FAILED"
    exit_code = 5


class QualityError(VSubError):
    code = "QUALITY_FAILED"
    exit_code = 3
