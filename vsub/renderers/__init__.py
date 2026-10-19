"""Document renderers and format dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..errors import RenderError, VSubError
from ..utils import ensure_dir, safe_filename
from .base import RenderContext
from .docx_renderer import render_docx
from .json_renderer import render_json
from .markdown_renderer import render_markdown
from .pdf_renderer import render_pdf
from .srt_renderer import render_srt
from .text_renderer import render_text

FORMAT_ALIASES = {
    "md": "md",
    "markdown": "md",
    "docx": "docx",
    "word": "docx",
    "doc": "docx",
    "pdf": "pdf",
    "txt": "txt",
    "text": "txt",
    "srt": "srt",
    "json": "json",
}


def normalize_formats(formats: Iterable[str] | str) -> list[str]:
    if isinstance(formats, str):
        formats = [part.strip() for part in formats.replace(";", ",").split(",")]
    result: list[str] = []
    for fmt in formats:
        key = FORMAT_ALIASES.get(str(fmt).strip().lower())
        if not key:
            raise RenderError(
                f"不支持的输出格式: {fmt}",
                hint="支持 md/docx/pdf/txt/srt/json。",
            )
        if key not in result:
            result.append(key)
    if not result:
        raise RenderError("至少需要一种输出格式。")
    return result


def default_stem(context: RenderContext) -> str:
    bvid = context.video.bvid
    suffix = f"_{bvid}" if bvid else ""
    return safe_filename(context.video.title, max_len=70) + suffix


def render_formats(
    context: RenderContext,
    formats: Iterable[str] | str,
    out_dir: str | Path,
    *,
    stem: str | None = None,
    output: str | Path | None = None,
    template: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    formats = normalize_formats(formats)
    out_dir = ensure_dir(out_dir)
    stem = stem or default_stem(context)
    output = Path(output) if output else None
    if output and len(formats) != 1:
        raise RenderError("--output 只能与单一输出格式一起使用。")

    outputs: dict[str, str] = {}
    errors: list[str] = []
    docx_path: Path | None = None

    def target(ext: str, key: str) -> Path:
        if output:
            return output
        return out_dir / f"{stem}.{ext}"

    for fmt in formats:
        try:
            if fmt == "md":
                path = render_markdown(context, target("md", fmt), template=template)
                outputs["md"] = str(path)
            elif fmt == "txt":
                path = render_text(context, target("txt", fmt))
                outputs["txt"] = str(path)
            elif fmt == "json":
                path = render_json(context, target("json", fmt))
                outputs["json"] = str(path)
            elif fmt == "srt":
                paths = render_srt(context, target("srt", fmt))
                if len(paths) == 1:
                    outputs["srt"] = str(paths[0])
                else:
                    for result, path in zip(context.parts, paths):
                        outputs[f"srt:p{result.part.index}"] = str(path)
            elif fmt == "docx":
                path = render_docx(context, target("docx", fmt))
                docx_path = path
                outputs["docx"] = str(path)
            elif fmt == "pdf":
                path = render_pdf(
                    context,
                    target("pdf", fmt),
                    docx_path=docx_path,
                )
                outputs["pdf"] = str(path)
        except VSubError as exc:
            errors.append(f"{fmt}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fmt}: {exc}")

    if not outputs:
        raise RenderError("所有输出格式都生成失败。", detail=errors)
    return outputs, errors


__all__ = [
    "FORMAT_ALIASES",
    "RenderContext",
    "default_stem",
    "normalize_formats",
    "render_docx",
    "render_formats",
    "render_json",
    "render_markdown",
    "render_pdf",
    "render_srt",
    "render_text",
]
