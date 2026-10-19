"""PDF renderer: LibreOffice conversion when available, ReportLab fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from ..errors import RenderError
from ..utils import ensure_dir, format_timestamp, human_duration, language_label
from .base import RenderContext, metadata_rows, source_label

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _convert_with_soffice(docx_path: Path, out: Path, soffice: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = out.parent / ".vsub_lo_profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [
            soffice,
            f"-env:UserInstallation=file:///{str(profile).replace(os.sep, '/')}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out.parent),
            str(docx_path),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise RenderError(f"LibreOffice 转 PDF 失败: {(proc.stderr or proc.stdout or '').strip()[:300]}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    produced = out.parent / (docx_path.stem + ".pdf")
    if produced != out:
        if not produced.exists():
            raise RenderError("LibreOffice 没有生成 PDF 文件。")
        produced.replace(out)
    return out


def _reportlab_render(context: RenderContext, out: Path) -> Path:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
            PageBreak,
        )
    except Exception as exc:  # noqa: BLE001
        raise RenderError(
            "没有可用的 PDF 引擎。",
            hint=(
                "安装 LibreOffice，或安装 ReportLab：\n"
                "  python -m pip install reportlab"
            ),
        ) from exc

    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except Exception:
        font_name = "Helvetica"

    def safe(text: object) -> str:
        return escape(str(text or "")).replace("\n", "<br/>")

    title_style = ParagraphStyle(
        "VSubTitle", fontName=font_name, fontSize=20, leading=27,
        textColor=colors.HexColor("#1F4E79"), spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "VSubMeta", fontName=font_name, fontSize=9, leading=13,
        textColor=colors.HexColor("#666666"), spaceAfter=2,
    )
    h1_style = ParagraphStyle(
        "VSubH1", fontName=font_name, fontSize=15, leading=21,
        textColor=colors.HexColor("#1F4E79"), spaceBefore=14, spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "VSubH2", fontName=font_name, fontSize=12, leading=17,
        textColor=colors.HexColor("#1F4E79"), spaceBefore=8, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "VSubBody", fontName=font_name, fontSize=10.5, leading=17,
        wordWrap="CJK", spaceAfter=5, alignment=TA_LEFT,
    )
    trans_style = ParagraphStyle(
        "VSubTrans", parent=body_style, fontSize=9.5, leading=15,
        textColor=colors.HexColor("#777777"), leftIndent=12,
    )
    small_style = ParagraphStyle(
        "VSubSmall", fontName=font_name, fontSize=8.5, leading=12,
        textColor=colors.HexColor("#888888"),
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawString(2 * cm, 1.2 * cm, "dsh-bilibili-subtitles")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=context.video.title,
        author="dsh-bilibili-subtitles",
    )
    story = [Paragraph(safe(context.video.title), title_style)]
    subtitle = "  ·  ".join(
        part
        for part in (context.video.owner, context.video.pubdate, human_duration(context.video.duration))
        if part
    )
    if subtitle:
        story.append(Paragraph(safe(subtitle), meta_style))
    if context.video.url:
        story.append(Paragraph(safe(context.video.url), meta_style))
    story.append(Spacer(1, 8))

    if context.parts:
        rows = [[Paragraph(f"<b>{safe(k)}</b>", small_style), Paragraph(safe(v), small_style)] for k, v in metadata_rows(context, context.parts[0])]
        table = Table(rows, colWidths=[3.2 * cm, 13.5 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F6FA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 10))

    for result in context.parts:
        heading_text = (
            f"P{result.part.index} · {result.part.part_title or result.part.title}"
            if context.multi_part
            else "正文"
        )
        story.append(Paragraph(safe(heading_text), h1_style))
        info = (
            f"字幕来源：{source_label(result)}　语言：{language_label(result.track.language)}　"
            f"片段：{len(result.track.segments)}"
        )
        story.append(Paragraph(safe(info), small_style))
        story.append(Spacer(1, 4))
        for paragraph in result.paragraphs:
            prefix = ""
            if context.include_timestamp:
                prefix += f'<font color="#999999">[{format_timestamp(paragraph.start)}]</font> '
            if paragraph.speaker:
                prefix += f"<b>{safe(paragraph.speaker)}：</b>"
            story.append(Paragraph(prefix + safe(paragraph.text), body_style))
            if context.bilingual and paragraph.translation:
                story.append(Paragraph(safe(paragraph.translation), trans_style))

    if context.include_quality:
        story.append(PageBreak())
        story.append(Paragraph("处理信息与质量报告", h1_style))
        quality = context.quality
        status = {"ok": "通过", "warn": "有警告", "fail": "失败"}.get(
            str(quality.get("status")), str(quality.get("status"))
        )
        lines = [
            f"状态：{status}　评分：{quality.get('score', '—')} / 100",
            f"时间覆盖率：{float(quality.get('coverage_ratio') or 0):.1%}　"
            f"片段：{quality.get('segments', 0)}　段落：{quality.get('paragraphs', 0)}",
            f"字符数：{quality.get('chars', 0)}　低置信度片段：{quality.get('low_confidence_segments', 0)}",
        ]
        for line in lines:
            story.append(Paragraph(safe(line), body_style))
        for warning in quality.get("warnings") or []:
            story.append(Paragraph("• " + safe(warning), small_style))
        story.append(Spacer(1, 10))
        story.append(
            Paragraph(
                "字幕由平台、UP 主或自动识别提供，可能存在错字、断句或时间轴误差；"
                "重要内容请对照原视频。请遵守版权与平台使用条款。",
                small_style,
            )
        )

    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception as exc:  # noqa: BLE001
        raise RenderError(f"ReportLab 生成 PDF 失败: {exc}") from exc
    return out


def render_pdf(
    context: RenderContext,
    out_path: str | Path,
    *,
    docx_path: str | Path | None = None,
    soffice: str | None = None,
) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    soffice = soffice or find_soffice()
    if soffice:
        try:
            if docx_path and Path(docx_path).exists():
                return _convert_with_soffice(Path(docx_path), out, soffice)
            from .docx_renderer import render_docx

            tmp_dir = out.parent / ".vsub_pdf_tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                temp_docx = tmp_dir / (out.stem + ".docx")
                render_docx(context, temp_docx)
                return _convert_with_soffice(temp_docx, out, soffice)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            # Fall through to ReportLab rather than failing if LO is broken.
            pass
    return _reportlab_render(context, out)
