from __future__ import annotations

import unittest

from vsub.models import Segment, SubtitleTrack
from vsub.quality import aggregate, analyze, compute_coverage


def track(*segments):
    return SubtitleTrack(source="external", language="zh", segments=list(segments))


class QualityTests(unittest.TestCase):
    def test_coverage_union(self):
        t = track(
            Segment(0, 5, "a"),
            Segment(4, 8, "b"),
            Segment(20, 30, "c"),
        )
        coverage, intervals = compute_coverage(t, 40)
        self.assertAlmostEqual(coverage, 18 / 40)
        self.assertEqual(intervals, [(0.0, 8.0), (20.0, 30.0)])

    def test_overlap_and_low_confidence_warnings(self):
        t = track(
            Segment(0, 5, "第一句", confidence=0.9),
            Segment(4, 8, "第二句", confidence=0.4),
        )
        report = analyze(t, [], video_duration=10)
        self.assertEqual(report["overlaps"], 1)
        self.assertEqual(report["low_confidence_segments"], 1)
        self.assertTrue(any("重叠" in w for w in report["warnings"]))
        self.assertEqual(report["status"], "warn")

    def test_empty_is_fail(self):
        report = analyze(SubtitleTrack(source="external", language=None, segments=[]), [], video_duration=10)
        self.assertEqual(report["status"], "fail")
        self.assertIn("NO_SEGMENTS", report["errors"])

    def test_aggregate(self):
        reports = [
            {"status": "ok", "score": 90, "segments": 2, "paragraphs": 1, "chars": 10, "duration": 10, "duration_covered": 0.9, "warnings": []},
            {"status": "warn", "score": 70, "segments": 3, "paragraphs": 2, "chars": 20, "duration": 20, "duration_covered": 0.8, "warnings": ["x"]},
        ]
        result = aggregate(reports, duration=30)
        self.assertEqual(result["status"], "warn")
        self.assertEqual(result["segments"], 5)
        self.assertEqual(result["paragraphs"], 3)
        self.assertAlmostEqual(result["duration_covered"], (9 + 16) / 30, places=3)


if __name__ == "__main__":
    unittest.main()
