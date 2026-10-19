"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .errors import VSubError
from .pipeline import Pipeline, PipelineOptions
from .renderers import normalize_formats
from .utils import json_dumps


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dsh-bilibili-subtitles",
        description=(
            "从 Bilibili 视频链接、本地视频或字幕文件生成 Markdown / Word / PDF / TXT / SRT 文档。"
            "优先使用平台字幕或外挂字幕，语音转写只做兜底。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python main.py https://www.bilibili.com/video/BV1xx411c7mD --format md,docx\n"
            "  python main.py BV1xx411c7mD --sessdata \"$env:BILIBILI_SESSDATA\" --bilingual\n"
            "  python main.py input.mp4 --subtitle input.srt --format docx\n"
            "  python main.py ./videos --format md,docx --out-dir output\n"
        ),
    )
    parser.add_argument("inputs", nargs="+", help="Bilibili 链接/BV 号、本地视频、字幕文件或目录")
    parser.add_argument(
        "-f",
        "--format",
        dest="formats",
        default="md",
        help="输出格式，逗号分隔：md,docx,pdf,txt,srt,json（默认 md）",
    )
    parser.add_argument("-o", "--output", help="单一输出文件路径（仅单输入 + 单格式）")
    parser.add_argument("--out-dir", default="output", help="输出目录（默认 output）")
    parser.add_argument("--title", help="覆盖文档标题（默认使用视频标题/文件名）")
    parser.add_argument("--subtitle", help="外挂字幕文件或目录（优先级最高）")
    parser.add_argument("--language", "--lang", dest="language", help="首选字幕/转写语言，如 zh、en、zh-CN")
    parser.add_argument("--bilingual", action="store_true", help="输出原文/译文双语对照")
    parser.add_argument("--timestamps", "--timestamp", dest="timestamps", action="store_true", default=True,
                        help="正文保留时间戳（默认开启）")
    parser.add_argument("--no-timestamps", "--no-timestamp", dest="timestamps", action="store_false",
                        help="正文不显示时间戳")
    parser.add_argument("--merge-sentences", dest="merge_sentences", action="store_true", default=True,
                        help="合并被硬切开的短句（默认开启）")
    parser.add_argument("--no-merge-sentences", dest="merge_sentences", action="store_false",
                        help="关闭短句合并")
    parser.add_argument("--no-auto-punctuation", dest="auto_punctuation", action="store_false",
                        default=True, help="关闭 ASR/OCR 的自动补标点")
    parser.add_argument("--speaker-diarization", action="store_true",
                        help="启用说话人区分（当前保留字幕中的 [说话人] 标记；自动 diarization 尚未启用）")
    parser.add_argument("--template", default="default", help="Markdown 模板：default/minimal 或模板文件路径")
    parser.add_argument("--pages", default="auto", help="视频分P：auto / all / 1,3-5（默认 auto）")
    parser.add_argument("--all-pages", dest="pages", action="store_const", const="all",
                        help="处理所有分P/剧集")
    parser.add_argument("--max-episodes", type=int, default=50, help="番剧最多处理集数（默认 50）")
    parser.add_argument("--quality-report", metavar="PATH", help="质量报告 JSON 路径（批量时为目录）")
    parser.add_argument("--no-quality", action="store_true", help="不生成质量报告，也不在文档中附加处理信息")
    parser.add_argument("--no-quality-appendix", action="store_true", help="文档末尾不附加质量报告")
    parser.add_argument("--no-intermediate", action="store_true", help="不写出清洗后的 segments JSON")

    auth = parser.add_argument_group("Bilibili 登录（平台字幕需要）")
    auth.add_argument("--sessdata", help="Bilibili SESSDATA，可只传值或完整 Cookie 字符串")
    auth.add_argument("--cookie", help="完整 Cookie 字符串，如 'SESSDATA=...; bili_jct=...'")
    auth.add_argument("--cookies", help="Netscape cookies.txt 或 JSON Cookie 文件")

    asr = parser.add_argument_group("ASR 兜底（可选）")
    asr.add_argument("--asr", dest="asr", action="store_true", default=None,
                     help="允许 Whisper 语音转写兜底（未安装 faster-whisper 时会提示安装）")
    asr.add_argument("--no-asr", dest="asr", action="store_false", help="禁止语音转写兜底")
    asr.add_argument("--asr-model", default="small", help="Whisper 模型：tiny/base/small/medium（默认 small）")
    asr.add_argument("--asr-device", default="auto", help="auto/cpu/cuda（默认 auto）")
    asr.add_argument("--asr-compute-type", help="int8/float16/float32（默认按设备选择）")
    asr.add_argument("--asr-language", help="转写语言（默认跟随 --language）")
    asr.add_argument("--model-dir", help="Whisper 模型缓存目录（默认 ./.vsub-models）")

    ocr = parser.add_argument_group("硬字幕 OCR（实验性，仅本地视频）")
    ocr.add_argument("--ocr", action="store_true", help="对本地视频硬字幕做 OCR")
    ocr.add_argument("--ocr-fps", type=float, default=2.0, help="抽帧帧率（默认 2）")
    ocr.add_argument("--ocr-crop", type=float, default=0.30, help="底部字幕区域高度比例（默认 0.30）")
    ocr.add_argument("--ocr-full-frame", action="store_true", help="对整帧 OCR（字幕位置不固定时使用）")
    ocr.add_argument("--ocr-min-confidence", type=float, default=0.5, help="OCR 最低置信度（默认 0.5）")

    parser.add_argument("--glossary", help="术语表 JSON（{'from': 'to'} 或 [['from','to']]）")
    parser.add_argument("--drop-pattern", action="append", dest="drop_patterns",
                        help="额外的广告/水印正则（可重复）")
    parser.add_argument("--ffmpeg", help="ffmpeg 可执行文件或目录")
    parser.add_argument("--work-dir", help="临时工作目录（默认系统临时目录）")
    parser.add_argument("--keep-temp", action="store_true", help="保留下载的音频/抽帧文件")
    parser.add_argument("--retries", type=int, default=3, help="HTTP 重试次数（默认 3）")
    parser.add_argument("--timeout", type=float, default=25.0, help="HTTP 超时秒数（默认 25）")
    parser.add_argument("--delay", type=float, default=0.4, help="请求间隔秒数（默认 0.4）")
    parser.add_argument("--strict", action="store_true", help="任一输入失败或质量 fail 时返回非零退出码")
    parser.add_argument("--json-summary", action="store_true", help="向 stdout 输出机器可读的处理摘要")
    parser.add_argument("--quiet", action="store_true", help="不打印进度日志")
    parser.add_argument("--verbose", action="store_true", help="打印详细日志")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _exit_code_for(errors: list[dict]) -> int:
    if not errors:
        return 0
    code = errors[0].get("code", "")
    if code in {"INPUT_ERROR", "UNSUPPORTED_INPUT", "BILIBILI_API_ERROR", "PARSE_ERROR"}:
        return 2
    if code in {"LOGIN_REQUIRED", "NO_SUBTITLE", "QUALITY_FAILED", "PROVIDER_ERROR"}:
        return 3
    if code == "DEPENDENCY_MISSING":
        return 4
    if code == "RENDER_FAILED":
        return 5
    return 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        formats = normalize_formats(args.formats)
    except VSubError as exc:
        parser.error(str(exc))
        return 2
    if args.output and len(formats) != 1:
        parser.error("--output 只能与单一输出格式一起使用（例如 --format docx --output out.docx）。")
    if args.speaker_diarization:  # documented limitation, not a failure
        print(
            "提示: 自动说话人分离尚未启用；会保留字幕中的 [说话人] 标记。",
            file=sys.stderr,
        )

    def logger(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    options = PipelineOptions(
        formats=formats,
        out_dir=args.out_dir,
        title=args.title,
        subtitle=args.subtitle,
        language=args.language,
        bilingual=args.bilingual,
        timestamps=args.timestamps,
        merge_sentences=args.merge_sentences,
        auto_punctuation=args.auto_punctuation,
        template=args.template,
        quality_appendix=not args.no_quality and not args.no_quality_appendix,
        write_quality=not args.no_quality,
        write_intermediate=not args.no_intermediate,
        quality_path=args.quality_report,
        output=args.output,
        pages=args.pages,
        max_episodes=args.max_episodes,
        sessdata=args.sessdata,
        cookie=args.cookie,
        cookies_file=args.cookies,
        glossary=args.glossary,
        drop_patterns=args.drop_patterns,
        asr=args.asr,
        asr_model=args.asr_model,
        asr_device=args.asr_device,
        asr_compute_type=args.asr_compute_type,
        asr_language=args.asr_language,
        model_dir=args.model_dir,
        ocr=args.ocr,
        ocr_fps=args.ocr_fps,
        ocr_crop=args.ocr_crop,
        ocr_full_frame=args.ocr_full_frame,
        ocr_min_confidence=args.ocr_min_confidence,
        ffmpeg=args.ffmpeg,
        work_dir=args.work_dir,
        keep_temp=args.keep_temp,
        retries=args.retries,
        timeout=args.timeout,
        delay=args.delay,
        verbose=args.verbose,
        strict=args.strict,
    )

    try:
        run = Pipeline(options, logger=logger).run(args.inputs)
    except VSubError as exc:
        print(f"错误 [{exc.code}]: {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"提示: {exc.hint}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130

    if args.json_summary:
        payload = {
            "ok": bool(run.results) and not run.errors,
            "out_dir": run.out_dir,
            "manifest": run.manifest_path,
            "results": [
                {
                    "title": r.video.title,
                    "bvid": r.video.bvid,
                    "parts": len(r.parts),
                    "outputs": r.outputs,
                    "quality": r.quality,
                }
                for r in run.results
            ],
            "errors": run.errors,
        }
        print(json_dumps(payload))
    elif not args.quiet:
        print("", file=sys.stderr)
        print(f"完成: {len(run.results)} 个视频，{len(run.errors)} 个错误", file=sys.stderr)
        for result in run.results:
            print(f"\n■ {result.video.title}", file=sys.stderr)
            for key, path in result.outputs.items():
                if key in {"quality", "segments"}:
                    continue
                print(f"  {key:4s}  {path}", file=sys.stderr)
            q = result.quality
            print(
                f"  质量: {q.get('status')} / {q.get('score')} 分 / "
                f"覆盖率 {float(q.get('coverage_ratio') or 0):.1%}",
                file=sys.stderr,
            )
        if run.manifest_path:
            print(f"\n清单: {run.manifest_path}", file=sys.stderr)

    if run.errors and not run.results:
        return _exit_code_for(run.errors)
    if args.strict:
        if run.errors:
            return _exit_code_for(run.errors)
        if any(r.quality.get("status") == "fail" for r in run.results):
            return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
