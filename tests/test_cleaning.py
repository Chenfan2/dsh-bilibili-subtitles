from __future__ import annotations

import unittest

from vsub.cleaners import CleanOptions, Glossary, clean_track
from vsub.cleaners.text import (
    dedupe_segments,
    drop_noise,
    join_texts,
    merge_short_segments,
    restore_punctuation,
    split_inline_bilingual,
    split_long_segments,
)
from vsub.models import Segment, SubtitleTrack
from vsub.utils import canonical_lang


def seg(start, end, text, speaker=None):
    return Segment(start=start, end=end, text=text, speaker=speaker)


class CleaningTests(unittest.TestCase):
    def test_merge_fragments(self):
        merged = merge_short_segments(
            [seg(0, 1, "这是"), seg(1.1, 3, "一个测试。")],
            max_gap=0.9,
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "这是一个测试。")

    def test_do_not_merge_across_sentence_end(self):
        merged = merge_short_segments(
            [seg(0, 2, "第一句。"), seg(2.1, 4, "第二句。")],
            max_gap=1.0,
        )
        self.assertEqual(len(merged), 2)

    def test_do_not_merge_different_speakers(self):
        merged = merge_short_segments(
            [seg(0, 2, "你好", "A"), seg(2.1, 3, "你好", "B")],
            max_gap=1.0,
        )
        self.assertEqual(len(merged), 2)

    def test_dedupe_repeated_caption(self):
        result = dedupe_segments([seg(0, 2, "重复"), seg(0.5, 2.5, "重复")])
        self.assertEqual(len(result), 1)

    def test_ad_removal(self):
        segments = [
            seg(0, 2, "正文第一句。"),
            seg(2, 4, "记得点赞、投币、收藏，"),
            seg(4, 6, "一键三连支持一下。"),
            seg(6, 8, "谢谢观看。"),
        ]
        kept = drop_noise(segments)
        self.assertEqual([s.text for s in kept], ["正文第一句。"])

    def test_content_with_attention_word_is_kept(self):
        kept = drop_noise([seg(0, 3, "关注这个问题的朋友可以看看下面的论文。")])
        self.assertEqual(len(kept), 1)

    def test_inline_bilingual(self):
        text, translation = split_inline_bilingual("中文一句\nAn English line.", "zh")
        self.assertEqual(text, "中文一句")
        self.assertEqual(translation, "An English line.")

    def test_join_english_spacing(self):
        self.assertEqual(join_texts(["Hello.", "World."]), "Hello. World.")
        self.assertEqual(join_texts(["你好。", "世界。"]), "你好。世界。")

    def test_clean_track_paragraphs_and_glossary(self):
        track = SubtitleTrack(
            source="external",
            language="zh",
            segments=[
                seg(0, 2, "我们用 DeepSeek 做研究。"),
                seg(2.1, 4, "先拆问题。"),
                seg(8, 10, "然后再写提纲。"),
            ],
        )
        cleaned, paragraphs = clean_track(
            track,
            CleanOptions(glossary=Glossary({"DeepSeek": "深度求索"})),
        )
        self.assertIn("深度求索", cleaned.segments[0].text)
        self.assertGreaterEqual(len(paragraphs), 2)
        self.assertEqual(cleaned.source, "external")

    def test_split_long_asr_block(self):
        text = "这是一个很长的语音识别结果。" * 20
        parts = split_long_segments([seg(0, 30, text)], max_chars=140)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p.text) <= 141 for p in parts))
        self.assertAlmostEqual(parts[-1].end, 30.0)
        self.assertGreater(parts[1].start, parts[0].start)

    def test_restore_punctuation_for_asr(self):
        result = restore_punctuation(seg(0, 8, "这是第一句但是第二句所以第三句"))
        self.assertEqual(result.text, "这是第一句但是第二句所以第三句。")
        already = restore_punctuation(seg(0, 8, "已经有标点。"))
        self.assertEqual(already.text, "已经有标点。")

    def test_default_is_not_german(self):
        self.assertIsNone(canonical_lang("default"))
        self.assertEqual(canonical_lang("de-DE"), "de")
        self.assertEqual(canonical_lang("zh-Hans"), "zh")

    def test_bilingual_inline_through_pipeline(self):
        track = SubtitleTrack(
            source="external",
            language="zh",
            segments=[
                seg(0, 3, "第一句。\nFirst sentence."),
                seg(3, 6, "第二句。\nSecond sentence."),
            ],
        )
        cleaned, paragraphs = clean_track(track, CleanOptions(bilingual=True))
        self.assertTrue(cleaned.meta["bilingual"])
        self.assertTrue(all(p.translation for p in paragraphs))


if __name__ == "__main__":
    unittest.main()
