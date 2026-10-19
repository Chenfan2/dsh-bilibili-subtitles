from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import make_context, workspace_dir
from vsub.models import Segment, SubtitleTrack
from vsub.renderers import render_docx, render_formats, render_json, render_markdown, render_srt


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.track = SubtitleTrack(
            source="external",
            language="zh",
            segments=[
                Segment(0, 2.5, "第一句测试。"),
                Segment(2.6, 5.0, "第二句测试。"),
            ],
        )
        self.context = make_context(self.track, duration=10)

    def test_markdown(self):
        out = workspace_dir("render_md") / "doc.md"
        render_markdown(self.context, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 测试视频", text)
        self.assertIn("[00:00] 第一句测试。", text)
        self.assertIn("质量报告", text)

    def test_srt(self):
        out = workspace_dir("render_srt") / "doc.srt"
        paths = render_srt(self.context, out)
        text = Path(paths[0]).read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:02,500", text)
        self.assertIn("第一句测试。", text)

    def test_json(self):
        out = workspace_dir("render_json") / "doc.json"
        render_json(self.context, out)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["video"]["title"], "测试视频")
        self.assertEqual(payload["parts"][0]["track"]["segments"][0]["text"], "第一句测试。")

    def test_docx_reopens(self):
        from docx import Document

        out = workspace_dir("render_docx") / "doc.docx"
        render_docx(self.context, out)
        doc = Document(str(out))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("测试视频", text)
        self.assertIn("第一句测试。", text)

    def test_all_formats(self):
        out_dir = workspace_dir("render_all")
        outputs, errors = render_formats(self.context, ["md", "txt", "srt", "json", "docx"], out_dir)
        self.assertEqual(errors, [])
        self.assertEqual(set(outputs), {"md", "txt", "srt", "json", "docx"})
        for path in outputs.values():
            self.assertTrue(Path(path).exists(), path)


if __name__ == "__main__":
    unittest.main()
