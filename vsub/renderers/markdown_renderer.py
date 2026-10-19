"""Markdown renderer with human-readable metadata, body and QA appendix."""

from __future__ import annotations

from pathlib import Path

from ..utils import ensure_dir, language_label
from .base import (
    RenderContext,
    apply_template,
    build_meta_table,
    build_toc,
    load_template,
    paragraph_line,
    quality_lines,
    source_label,
)


def _body(context: RenderContext) -> str:
    blocks: list[str] = []
    for result in context.parts:
        if context.multi_part:
            title = f"P{result.part.index} · {result.part.part_title or result.part.title}"
            blocks.append(f"## {title}")
            blocks.append("")
            blocks.append(
                f"> 字幕来源：{source_label(result)} · "
                f"语言：{language_label(result.track.language)} · "
                f"{len(result.track.segments)} 段"
            )
            blocks.append("")
        if not result.paragraphs:
            blocks.append("_（没有可用字幕）_")
            blocks.append("")
            continue
        for paragraph in result.paragraphs:
            blocks.append(paragraph_line(context, result, paragraph))
            blocks.append("")
    return "\n".join(blocks).strip()


def _quality(context: RenderContext) -> str:
    if not context.include_quality:
        return ""
    lines = ["## 质量报告", ""]
    lines.extend(quality_lines(context.quality))
    lines.append("")
    lines.append(
        "> 由 `dsh-bilibili-subtitles` 自动生成。字幕由平台/UP 主/自动识别提供，"
        "可能存在错字、断句或时间轴误差；重要内容请对照原视频。"
    )
    return "\n".join(lines)


def render_markdown(
    context: RenderContext,
    out_path: str | Path,
    *,
    template: str | None = None,
) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    template_text = load_template(template or context.template or "default")
    first = context.parts[0] if context.parts else None
    meta_table = build_meta_table(context, first) if first else ""
    values = {
        "title": context.video.title,
        "meta_table": meta_table,
        "toc": build_toc(context),
        "body": _body(context),
        "content": _body(context),
        "quality": _quality(context),
        "source_url": context.video.url or "",
        "generated_at": context.generated_at,
    }
    text = apply_template(template_text, values)
    out.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
    return out
