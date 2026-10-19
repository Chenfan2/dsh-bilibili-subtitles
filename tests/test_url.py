from __future__ import annotations

import unittest

from vsub.bilibili import parse_bilibili_link
from vsub.errors import UnsupportedInputError


class UrlTests(unittest.TestCase):
    def test_bv_and_av(self):
        self.assertEqual(parse_bilibili_link("BV1GJ411x7h7").bvid, "BV1GJ411x7h7")
        self.assertEqual(parse_bilibili_link("av80433022").aid, 80433022)

    def test_video_url_and_page(self):
        parsed = parse_bilibili_link("https://www.bilibili.com/video/BV1GJ411x7h7/?p=2&t=10")
        self.assertEqual(parsed.kind, "video")
        self.assertEqual(parsed.bvid, "BV1GJ411x7h7")
        self.assertEqual(parsed.page, 2)

    def test_short_link_and_share_text(self):
        self.assertEqual(parse_bilibili_link("https://b23.tv/abc123").kind, "short")
        self.assertEqual(
            parse_bilibili_link("看这个 https://b23.tv/abc123 很有意思").kind,
            "short",
        )

    def test_bangumi(self):
        ep = parse_bilibili_link("https://www.bilibili.com/bangumi/play/ep123456")
        self.assertEqual(ep.kind, "bangumi_ep")
        self.assertEqual(ep.ep_id, 123456)
        season = parse_bilibili_link("https://www.bilibili.com/bangumi/play/ss28747")
        self.assertEqual(season.kind, "bangumi_ss")
        self.assertEqual(season.season_id, 28747)

    def test_non_bilibili(self):
        with self.assertRaises(UnsupportedInputError):
            parse_bilibili_link("https://example.com/video/BV1GJ411x7h7")
        with self.assertRaises(UnsupportedInputError):
            parse_bilibili_link("not a link")


if __name__ == "__main__":
    unittest.main()
