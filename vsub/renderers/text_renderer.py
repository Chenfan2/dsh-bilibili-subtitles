"""Plain-text renderer."""

from __future__ import annotations

from pathlib import Path

from ..utils import ensure_dir, format_timestamp, human_duration, language_label
from .base import RenderContext, source_label


def render_text(context: RenderContext, out_path: str | Path) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    lines: list[str] = [context.video.title, "=" * min(60, max(8, len(context.video.title))), ""]
    if context.video.owner:
        lines.append(f"UP 主: {context.video.owner}")
    if context.video.pubdate:
        lines.append(f"发布时间: {context.video.pubdate}")
    lines.append(f"视频时长: {human_duration(context.video.duration)}")
    if context.video.url:
        lines.append(f"视频链接: {context.video.url}")
    lines.append(f"生成时间: {context.generated_at}")
    lines.append("")

    for result in context.parts:
        if context.multi_part:
            lines.append("")
            lines.append(f"P{result.part.index} · {result.part.part_title or result.part.title}")
            lines.append("-" * 40)
        lines.append(
            f"字幕: {source_label(result)} / {language_label(result.track.language)} / "
            f"{len(result.track.segments)} 段"
        )
        lines.append("")
        for paragraph in result.paragraphs:
            prefix = f"[{format_timestamp(paragraph.start)}] " if context.include_timestamp else ""
            if paragraph.speaker:
                prefix += f"{paragraph.speaker}: "
            lines.append(prefix + paragraph.text)
            if context.bilingual and paragraph.translation:
                lines.append("  " + paragraph.translation)
            lines.append("")
    lines.append("")
    lines.append("（字幕由平台/UP 主/自动识别提供，可能存在误差，请对照原视频。）")
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return out
