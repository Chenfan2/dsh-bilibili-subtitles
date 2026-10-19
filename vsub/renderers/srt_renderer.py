"""SRT renderer (one file per part)."""

from __future__ import annotations

from pathlib import Path

from ..errors import RenderError
from ..utils import ensure_dir, format_timestamp
from .base import RenderContext


def _cue_text(paragraph_text: str) -> str:
    return paragraph_text.replace("\r", "").strip()


def render_srt(context: RenderContext, out_path: str | Path) -> list[Path]:
    out = Path(out_path)
    if out.suffix.lower() != ".srt":
        out = out.with_suffix(".srt")
    ensure_dir(out.parent)
    paths: list[Path] = []
    for result in context.parts:
        if not result.track.segments:
            raise RenderError(f"P{result.part.index} 没有字幕片段，无法生成 SRT。")
        if context.multi_part:
            part_path = out.with_name(f"{out.stem}.p{result.part.index}{out.suffix}")
        else:
            part_path = out
        blocks: list[str] = []
        for i, seg in enumerate(result.track.segments, start=1):
            start = max(0.0, seg.start)
            end = max(start + 0.05, seg.end)
            text = _cue_text(seg.text)
            if seg.speaker:
                text = f"[{seg.speaker}] {text}"
            if context.bilingual and seg.translation:
                text += "\n" + _cue_text(seg.translation)
            blocks.append(
                f"{i}\n{format_timestamp(start, 'srt')} --> {format_timestamp(end, 'srt')}\n{text}\n"
            )
        part_path.write_text("\n".join(blocks), encoding="utf-8", newline="\n")
        paths.append(part_path)
    return paths
