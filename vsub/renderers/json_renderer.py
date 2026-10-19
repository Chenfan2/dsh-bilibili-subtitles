"""Structured JSON output for downstream tooling."""

from __future__ import annotations

from pathlib import Path

from ..utils import ensure_dir, json_dumps
from .base import RenderContext


def render_json(context: RenderContext, out_path: str | Path) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    payload = {
        "schema": "dsh-bilibili-subtitles/v1",
        "generated_at": context.generated_at,
        "video": context.video.to_dict(),
        "parts": [part.to_dict() for part in context.parts],
        "quality": context.quality,
        "options": {
            "timestamps": context.include_timestamp,
            "bilingual": context.bilingual,
            "template": context.template,
        },
    }
    out.write_text(json_dumps(payload), encoding="utf-8", newline="\n")
    return out
