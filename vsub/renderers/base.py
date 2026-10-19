"""Shared rendering context and metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import PartResult, VideoInfo
from ..utils import format_timestamp, human_duration, language_label

SOURCE_LABELS = {
    "bilibili": "Bilibili 平台字幕",
    "external": "外挂字幕",
    "embedded": "视频内嵌字幕",
    "asr": "Whisper 语音转写",
    "ocr": "硬字幕 OCR",
}


@dataclass
class RenderContext:
    video: VideoInfo
    parts: list[PartResult]
    quality: dict
    generated_at: str
    include_timestamp: bool = True
    bilingual: bool = False
    include_quality: bool = True
    template: str = "default"
    extra: dict = field(default_factory=dict)

    @property
    def multi_part(self) -> bool:
        return len(self.parts) > 1


def source_label(result: PartResult) -> str:
    base = SOURCE_LABELS.get(result.track.source, result.track.source)
    if result.track.source == "bilibili":
        if result.track.meta.get("is_ai"):
            return base + "（AI 字幕）"
        if result.track.meta.get("author"):
            return base + "（CC 字幕）"
    return base


def subtitle_type(result: PartResult) -> str:
    if result.track.source == "bilibili":
        return "AI 生成" if result.track.meta.get("is_ai") else "平台/CC"
    return SOURCE_LABELS.get(result.track.source, result.track.source)


def md_escape(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def metadata_rows(context: RenderContext, result: PartResult) -> list[tuple[str, str]]:
    video = context.video
    rows: list[tuple[str, str]] = []
    rows.append(("视频标题", video.title))
    if video.owner:
        rows.append(("UP 主", video.owner))
    if video.pubdate:
        rows.append(("发布时间", video.pubdate))
    rows.append(("视频时长", human_duration(video.duration or result.part.duration)))
    if video.url:
        rows.append(("视频链接", video.url))
    if video.bvid:
        rows.append(("BV 号", video.bvid))
    if result.part.ep_id:
        rows.append(("EP 号", f"ep{result.part.ep_id}"))
    if context.multi_part:
        rows.append(("分P", f"P{result.part.index} · {result.part.part_title or ''}".strip(" ·")))
    rows.append(("字幕来源", source_label(result)))
    rows.append(("字幕语言", language_label(result.track.language)))
    if result.track.confidence is not None:
        rows.append(("平均置信度", f"{result.track.confidence:.0%}"))
    rows.append(("字幕片段", f"{len(result.track.segments)} 段 / {len(result.paragraphs)} 段正文"))
    if result.track.meta.get("bilingual"):
        coverage = result.track.meta.get("translation_coverage")
        rows.append(("双语对齐", f"{coverage:.0%}" if isinstance(coverage, (int, float)) else "是"))
    rows.append(("生成时间", context.generated_at))
    return rows


def quality_lines(quality: dict) -> list[str]:
    status = quality.get("status", "unknown")
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(status, "•")
    lines = [
        f"- 状态：{icon} **{status}**",
        f"- 评分：{quality.get('score', '—')} / 100",
        f"- 时间覆盖率：{float(quality.get('coverage_ratio') or 0):.1%}"
        + (
            f"（内容区间 {float(quality.get('coverage_span')):.1%}）"
            if quality.get("coverage_span") is not None
            else ""
        ),
        f"- 片段 / 段落：{quality.get('segments', 0)} / {quality.get('paragraphs', 0)}",
        f"- 字符数：{quality.get('chars', 0)}",
    ]
    if quality.get("low_confidence_segments"):
        lines.append(f"- 低置信度片段：{quality['low_confidence_segments']}")
    if quality.get("gaps_over_10s"):
        lines.append(f"- 10 秒以上空白：{quality['gaps_over_10s']} 段")
    warnings = quality.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("**警告：**")
        lines.extend(f"- {warning}" for warning in warnings)
    return lines


def build_meta_table(context: RenderContext, result: PartResult) -> str:
    rows = metadata_rows(context, result)
    lines = ["| 项目 | 内容 |", "| --- | --- |"]
    for label, value in rows:
        if label == "视频链接" and value:
            lines.append(f"| {md_escape(label)} | [{md_escape(value)}]({value}) |")
        else:
            lines.append(f"| {md_escape(label)} | {md_escape(value)} |")
    return "\n".join(lines)


def build_toc(context: RenderContext) -> str:
    if not context.multi_part:
        return ""
    lines = ["## 目录", ""]
    for result in context.parts:
        title = f"P{result.part.index} · {result.part.part_title or result.part.title}"
        lines.append(f"- {title}")
    return "\n".join(lines)


def paragraph_line(context: RenderContext, result: PartResult, paragraph) -> str:
    prefix = ""
    if context.include_timestamp:
        prefix += f"[{format_timestamp(paragraph.start)}] "
    if paragraph.speaker:
        prefix += f"**{paragraph.speaker}**："
    line = prefix + paragraph.text
    if context.bilingual and paragraph.translation:
        line += f"\n> {paragraph.translation}"
    return line


def load_template(name_or_path: str) -> str:
    p = Path(name_or_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    candidates = [template_dir / f"{name_or_path}.md", template_dir / name_or_path]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    # Built-in fallback, so a missing template never blocks output.
    return "# {{title}}\n\n{{meta_table}}\n\n{{toc}}\n\n## 正文\n\n{{body}}\n\n{{quality}}\n"


def apply_template(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    return result
