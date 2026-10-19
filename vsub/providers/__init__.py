"""Subtitle providers, ordered from highest to lowest fidelity."""

from .asr import ASRSubtitleProvider
from .base import SubtitleProvider
from .bilibili import BilibiliSubtitleProvider
from .embedded import EmbeddedSubtitleProvider
from .external import ExternalSubtitleProvider
from .ocr import OCRSubtitleProvider

__all__ = [
    "ASRSubtitleProvider",
    "BilibiliSubtitleProvider",
    "EmbeddedSubtitleProvider",
    "ExternalSubtitleProvider",
    "OCRSubtitleProvider",
    "SubtitleProvider",
]
