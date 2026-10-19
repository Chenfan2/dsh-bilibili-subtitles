from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vsub.pipeline import Pipeline, PipelineOptions  # noqa: E402
from tests.mock_server import MockBilibiliServer  # noqa: E402

_TMP_ROOT = ROOT / "tests" / "_tmp"


def workspace_temp(name: str) -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / name
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


class MockPipelineTest(unittest.TestCase):
    def test_bilibili_url_to_markdown_and_docx(self):
        tmp = workspace_temp("mock_ok")
        with MockBilibiliServer() as mock:
            options = PipelineOptions(
                formats=["md", "docx", "json"],
                out_dir=str(tmp),
                api_base=mock.api_base,
                pages="auto",
                write_quality=True,
                write_intermediate=True,
                asr=False,
                # No external network: the mock serves view + subtitle JSON.
            )
            run = Pipeline(options, logger=lambda _m: None).run(
                ["https://www.bilibili.com/video/BV1xx411c7mD"]
            )
            self.assertFalse(run.errors)
            self.assertEqual(len(run.results), 1)
            result = run.results[0]
            self.assertEqual(result.video.title, "测试视频：AI 与研究工作流")
            self.assertEqual(result.parts[0].track.source, "bilibili")
            self.assertTrue(result.parts[0].track.meta["is_ai"])
            self.assertEqual(len(result.parts[0].track.segments), 4)
            md = Path(result.outputs["md"]).read_text(encoding="utf-8")
            self.assertIn("这是第一句测试字幕", md)
            self.assertIn("DeepSeek", md)
            self.assertIn("质量报告", md)
            self.assertTrue(Path(result.outputs["docx"]).exists())
            self.assertTrue(Path(result.outputs["quality"]).exists())
            quality = json.loads(Path(result.outputs["quality"]).read_text(encoding="utf-8"))
            self.assertEqual(quality["parts"][0]["subtitle"]["source"], "bilibili")
            self.assertIn("attempts", quality["parts"][0])

    def test_dual_subtitle_bilingual(self):
        tmp = workspace_temp("mock_bilingual")
        with MockBilibiliServer() as mock:
            mock.server.dual_subtitles = True
            options = PipelineOptions(
                formats=["md"],
                out_dir=str(tmp),
                api_base=mock.api_base,
                bilingual=True,
                language="zh",
                asr=False,
            )
            run = Pipeline(options, logger=lambda _m: None).run(
                ["https://www.bilibili.com/video/BV1xx411c7mD"]
            )
            self.assertFalse(run.errors)
            result = run.results[0]
            self.assertEqual(len(result.parts[0].track.meta.get("secondary_language", "")), 5)
            self.assertTrue(result.parts[0].paragraphs[0].translation)
            md = Path(result.outputs["md"]).read_text(encoding="utf-8")
            self.assertIn("This is the first test caption", md)

    def test_multi_part_document_and_srt(self):
        tmp = workspace_temp("mock_multi")
        with MockBilibiliServer() as mock:
            mock.server.multi_pages = True
            options = PipelineOptions(
                formats=["md", "srt"],
                out_dir=str(tmp),
                api_base=mock.api_base,
                pages="all",
                asr=False,
            )
            run = Pipeline(options, logger=lambda _m: None).run(
                ["https://www.bilibili.com/video/BV1xx411c7mD"]
            )
            self.assertFalse(run.errors)
            result = run.results[0]
            self.assertEqual(len(result.parts), 2)
            self.assertIn("srt:p1", result.outputs)
            self.assertIn("srt:p2", result.outputs)
            md = Path(result.outputs["md"]).read_text(encoding="utf-8")
            self.assertIn("P1 · 正片", md)
            self.assertIn("P2 · 第二P", md)

    def test_missing_login_is_reported(self):
        # An empty subtitle list without SESSDATA must produce a clear login hint.
        tmp = workspace_temp("mock_login")
        with MockBilibiliServer() as mock:
            mock.server.empty_subtitles = True
            options = PipelineOptions(
                formats=["md"],
                out_dir=str(tmp),
                api_base=mock.api_base,
                asr=False,
            )
            run = Pipeline(options, logger=lambda _m: None).run(
                ["https://www.bilibili.com/video/BV1xx411c7mD"]
            )
            self.assertFalse(run.results)
            self.assertEqual(run.errors[0]["code"], "LOGIN_REQUIRED")
            self.assertIn("SESSDATA", run.errors[0]["hint"])
            self.assertTrue(list(Path(tmp).glob("*.error.json")))


if __name__ == "__main__":
    unittest.main()
