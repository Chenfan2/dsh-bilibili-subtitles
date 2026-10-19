from __future__ import annotations

import unittest
from pathlib import Path

from vsub.providers.ffmpeg import find_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "tests" / "fixtures" / "ocr_video.mp4"


def _ocr_ready() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    ffmpeg, _ = find_ffmpeg()
    return bool(ffmpeg and VIDEO.exists())


@unittest.skipUnless(_ocr_ready(), "RapidOCR/ffmpeg not installed; optional OCR test")
class OCRTest(unittest.TestCase):
    def test_hardcoded_subtitle(self):
        from tests.helpers import workspace_dir
        from vsub.providers.ocr import OCRSubtitleProvider

        work = workspace_dir("ocr_provider")
        provider = OCRSubtitleProvider(
            VIDEO,
            fps=1.0,
            crop_ratio=0.30,
            workdir=work,
        )
        track = provider.fetch()
        self.assertTrue(track.segments)
        self.assertIn("人工智能", track.segments[0].text)
        self.assertEqual(track.language, "zh")


if __name__ == "__main__":
    unittest.main()
