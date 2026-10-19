from __future__ import annotations

import unittest

from vsub.parsers import parse_subtitle_text


class ParserTests(unittest.TestCase):
    def test_srt_bom_html_and_missing_blank_lines(self):
        text = (
            "\ufeff1\n00:00:01,000 --> 00:00:03,000\n<b>第一句</b>\n"
            "2\n00:00:03,100 --> 00:00:05,500\n[张三] 第二句\n"
        )
        track = parse_subtitle_text(text, hint=".srt")
        self.assertEqual(len(track.segments), 2)
        self.assertEqual(track.segments[0].text, "第一句")
        self.assertEqual(track.segments[1].speaker, "张三")
        self.assertEqual(track.segments[1].text, "第二句")

    def test_srt_ass_override_tags(self):
        text = "1\n00:00:00,000 --> 00:00:02,000\n{\\an8}你好\\N世界\n"
        track = parse_subtitle_text(text, hint=".srt")
        self.assertEqual(track.segments[0].text, "你好\n世界")

    def test_vtt_voice_and_short_timestamps(self):
        text = (
            "WEBVTT\nLanguage: zh\n\n"
            "NOTE a comment\n\n"
            "00:01.000 --> 00:03.000 align:start\n<v 张三>你好\n\n"
            "00:03.000 --> 00:05.000\n<v 李四>世界\n"
        )
        track = parse_subtitle_text(text, hint=".vtt")
        self.assertEqual(len(track.segments), 2)
        self.assertEqual(track.segments[0].speaker, "张三")
        self.assertEqual(track.segments[0].start, 1.0)
        self.assertEqual(track.segments[1].speaker, "李四")

    def test_ass(self):
        text = (
            "[Script Info]\nTitle: x\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:03.50,Default,张三,0,0,0,,{\\an8}第一句\\N第二行\n"
            "Comment: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,注释\n"
        )
        track = parse_subtitle_text(text, hint=".ass")
        self.assertEqual(len(track.segments), 1)
        self.assertEqual(track.segments[0].speaker, "张三")
        self.assertEqual(track.segments[0].end, 3.5)
        self.assertIn("第二行", track.segments[0].text)

    def test_bilibili_json(self):
        data = {
            "body": [
                {"from": 0, "to": 2.5, "text": "第一句"},
                {"from": 2.5, "to": 5, "text": "第二句"},
            ]
        }
        track = parse_subtitle_text(__import__("json").dumps(data), hint=".json")
        self.assertEqual(len(track.segments), 2)
        self.assertEqual(track.segments[0].start, 0.0)
        self.assertEqual(track.segments[1].end, 5.0)

    def test_plain_timestamp_lines(self):
        track = parse_subtitle_text("[00:12] 你好\n[00:15] 世界\n", hint=".txt")
        self.assertEqual(len(track.segments), 2)
        self.assertEqual(track.segments[0].start, 12.0)


if __name__ == "__main__":
    unittest.main()
