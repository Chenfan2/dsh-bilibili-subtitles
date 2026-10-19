"""End-to-end pipeline: input -> subtitle acquisition -> clean -> render -> QA."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .bilibili import BilibiliClient
from .cleaners import CleanOptions, Glossary, clean_track
from .errors import (
    DependencyMissingError,
    InputError,
    LoginRequiredError,
    NoSubtitleError,
    ParseError,
    ProviderError,
    VSubError,
)
from .input_adapter import InputItem, discover_inputs
from .models import PartResult, Segment, SubtitleTrack, VideoInfo, VideoPart, VideoResult
from .parsers import parse_subtitle_file
from .probe import probe_media
from .providers import (
    ASRSubtitleProvider,
    BilibiliSubtitleProvider,
    EmbeddedSubtitleProvider,
    ExternalSubtitleProvider,
    OCRSubtitleProvider,
)
from .quality import aggregate, analyze
from .renderers import RenderContext, default_stem, render_formats, render_json
from .utils import (
    canonical_lang,
    ensure_dir,
    json_dumps,
    now_local_iso,
    safe_filename,
)


@dataclass
class PipelineOptions:
    formats: list[str] = field(default_factory=lambda: ["md"])
    out_dir: str = "output"
    title: str | None = None
    subtitle: str | None = None
    language: str | None = None
    bilingual: bool = False
    timestamps: bool = True
    merge_sentences: bool = True
    auto_punctuation: bool = True
    template: str = "default"
    quality_appendix: bool = True
    write_quality: bool = True
    write_intermediate: bool = True
    quality_path: str | None = None
    output: str | None = None
    pages: str = "auto"
    max_episodes: int = 50
    sessdata: str | None = None
    cookie: str | None = None
    cookies_file: str | None = None
    glossary: str | None = None
    drop_patterns: list[str] | None = None
    asr: bool | None = None  # None = auto fallback, True = allow, False = disabled
    asr_model: str = "small"
    asr_device: str = "auto"
    asr_compute_type: str | None = None
    asr_language: str | None = None
    model_dir: str | None = None
    ocr: bool = False
    ocr_fps: float = 2.0
    ocr_crop: float = 0.30
    ocr_full_frame: bool = False
    ocr_min_confidence: float = 0.5
    ffmpeg: str | None = None
    work_dir: str | None = None
    keep_temp: bool = False
    delay: float = 0.4
    retries: int = 3
    timeout: float = 25.0
    verbose: bool = False
    strict: bool = False
    api_base: str | None = None
    warmup: bool = False


@dataclass
class RunResult:
    results: list[VideoResult]
    errors: list[dict]
    out_dir: str
    manifest_path: str | None = None


def _attempt(provider: str, status: str, message: str = "", elapsed: float = 0.0) -> dict:
    return {
        "provider": provider,
        "status": status,
        "message": message,
        "elapsed_ms": int(elapsed * 1000),
    }


class Pipeline:
    def __init__(self, options: PipelineOptions, logger: Callable[[str], None] | None = None):
        self.options = options
        self.log = logger or (lambda msg: print(msg, flush=True))
        try:
            self.out_dir = ensure_dir(options.out_dir)
        except OSError as exc:
            raise InputError(
                f"无法创建输出目录: {options.out_dir} ({exc})",
                hint="输出目录必须位于当前会话工作区内，或改用 --out-dir 指向可写目录。",
            ) from exc
        env_cookie = os.environ.get("BILIBILI_COOKIE")
        env_sess = os.environ.get("BILIBILI_SESSDATA")
        cookie = options.cookie
        if not cookie and options.sessdata:
            cookie = options.sessdata if "=" in options.sessdata else f"SESSDATA={options.sessdata}"
        if not cookie and env_cookie:
            cookie = env_cookie
        if not cookie and env_sess:
            cookie = f"SESSDATA={env_sess}"
        self.cookie = cookie
        self.glossary = Glossary.from_file(options.glossary) if options.glossary else None
        self._used_stems: set[str] = set()
        self._work_root: Path | None = None
        self._owns_work_root = False

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def run(self, inputs: list[str]) -> RunResult:
        options = self.options
        items = discover_inputs(inputs, subtitle=options.subtitle)
        if options.output and len(items) > 1:
            raise VSubError("--output 只能用于单个输入；批量请使用 --out-dir。")
        if options.quality_path and len(items) > 1:
            ensure_dir(options.quality_path)

        try:
            if options.work_dir:
                self._work_root = ensure_dir(options.work_dir)
            else:
                # Keep temp files inside the workspace/output tree. System temp
                # directories are often outside the DSH write sandbox.
                self._work_root = ensure_dir(self.out_dir / ".vsub-tmp")
                self._owns_work_root = True
        except OSError as exc:
            raise InputError(
                f"无法创建临时工作目录: {exc}",
                hint="用 --work-dir 指向会话工作区内的可写目录。",
            ) from exc

        results: list[VideoResult] = []
        errors: list[dict] = []
        total = len(items)
        try:
            for i, item in enumerate(items, start=1):
                self.log(f"[{i}/{total}] {item.raw}")
                try:
                    result = self._process_item(item, index=i, total=total)
                    results.append(result)
                except VSubError as exc:
                    error = {
                        "input": item.raw,
                        "code": exc.code,
                        "message": exc.message,
                        "hint": exc.hint,
                        "detail": _safe_detail(exc.detail),
                        "generated_at": now_local_iso(),
                    }
                    errors.append(error)
                    self.log(f"  ✗ {exc.code}: {exc.message}")
                    if exc.hint:
                        self.log(f"    提示: {exc.hint}")
                    self._write_error(item, error)
                except Exception as exc:  # noqa: BLE001
                    error = {
                        "input": item.raw,
                        "code": "UNEXPECTED_ERROR",
                        "message": str(exc),
                        "hint": "使用 --verbose 查看更详细日志，或提交 issue。",
                        "generated_at": now_local_iso(),
                    }
                    errors.append(error)
                    self.log(f"  ✗ UNEXPECTED_ERROR: {exc}")
                    self._write_error(item, error)
        finally:
            self._cleanup()

        manifest_path = self._write_manifest(results, errors)
        return RunResult(
            results=results,
            errors=errors,
            out_dir=str(self.out_dir),
            manifest_path=str(manifest_path) if manifest_path else None,
        )

    # ------------------------------------------------------------------
    # One input
    # ------------------------------------------------------------------
    def _process_item(self, item: InputItem, *, index: int, total: int) -> VideoResult:
        prefetched: SubtitleTrack | None = None
        if item.kind == "subtitle":
            assert item.subtitle_path is not None
            prefetched = parse_subtitle_file(
                item.subtitle_path, source="external", language=self.options.language
            )
            title = prefetched.meta.get("file") and Path(prefetched.meta["file"]).stem or item.hint
            duration = prefetched.duration
            video = VideoInfo(
                input=item.raw,
                platform="local",
                title=title,
                duration=duration,
                parts=[
                    VideoPart(
                        index=1,
                        title=title,
                        duration=duration,
                        url=None,
                    )
                ],
            )
            client = None
        elif item.kind == "video":
            assert item.video_path is not None
            probe = probe_media(item.video_path, self.options.ffmpeg)
            video = VideoInfo(
                input=item.raw,
                platform="local",
                title=probe.title,
                owner=probe.owner,
                duration=probe.duration,
                parts=[
                    VideoPart(
                        index=1,
                        title=probe.title,
                        duration=probe.duration,
                        url=None,
                    )
                ],
                extra={
                    "file": str(item.video_path),
                    "has_subtitle_stream": probe.has_subtitle_stream,
                    "resolution": f"{probe.width}x{probe.height}" if probe.width and probe.height else None,
                },
            )
            client = None
        else:
            client = BilibiliClient(
                cookie=self.cookie,
                cookies_file=self.options.cookies_file,
                timeout=self.options.timeout,
                retries=self.options.retries,
                delay=self.options.delay,
                api_base=self.options.api_base or "https://api.bilibili.com",
                warmup=self.options.warmup,
                logger=self.log if self.options.verbose else None,
            )
            video = client.resolve(
                item.raw,
                pages=self.options.pages,
                max_episodes=self.options.max_episodes,
            )
            self.log(
                f"  {video.title} / {video.owner or '未知 UP 主'} / "
                f"{len(video.parts)} 个分P / {video.duration:.0f}s"
            )

        if self.options.title:
            video.title = self.options.title
            if len(video.parts) == 1:
                video.parts[0].title = self.options.title
                video.parts[0].part_title = None

        part_results: list[PartResult] = []
        part_errors: list[dict] = []
        for part in video.parts:
            try:
                result = self._process_part(
                    video,
                    part,
                    item,
                    client=client,
                    prefetched=prefetched,
                )
                part_results.append(result)
                self.log(
                    f"  P{part.index}: {result.track.source} / "
                    f"{len(result.track.segments)} 段 / 覆盖率 "
                    f"{result.quality.get('coverage_ratio', 0):.0%}"
                )
            except VSubError as exc:
                part_errors.append(
                    {
                        "part": part.index,
                        "code": exc.code,
                        "message": exc.message,
                        "hint": exc.hint,
                        "detail": _safe_detail(exc.detail),
                    }
                )
                self.log(f"  P{part.index}: ✗ {exc.code}: {exc.message}")
                if len(video.parts) == 1:
                    raise

        if not part_results:
            raise NoSubtitleError(
                "所有分P都没有成功获取字幕。",
                detail=part_errors,
            )

        if len(part_results) == 1:
            # Keep the detailed single-part metrics (paragraph count, samples)
            # instead of flattening them through the aggregate report.
            quality = dict(part_results[0].quality)
        else:
            quality = aggregate(
                [p.quality for p in part_results],
                duration=video.duration,
            )
        if part_errors:
            quality["status"] = "fail" if quality.get("status") == "fail" else "warn"
            for err in part_errors:
                quality.setdefault("warnings", []).append(
                    f"P{err['part']} 失败：{err['message']}"
                )
            quality["part_errors"] = part_errors

        context = RenderContext(
            video=video,
            parts=part_results,
            quality=quality,
            generated_at=now_local_iso(),
            include_timestamp=self.options.timestamps,
            bilingual=self.options.bilingual,
            include_quality=self.options.quality_appendix,
            template=self.options.template,
        )
        base_stem = default_stem(context)
        stem = self._unique_stem(base_stem)
        outputs, render_errors = render_formats(
            context,
            self.options.formats,
            self.out_dir,
            stem=stem,
            output=self.options.output if total == 1 else None,
            template=self.options.template if self.options.template not in {"default", "minimal"} else None,
        )
        if render_errors:
            quality.setdefault("warnings", []).extend(render_errors)
            if quality.get("status") == "ok":
                quality["status"] = "warn"

        if self.options.write_intermediate:
            segments_path = self.out_dir / f"{stem}.segments.json"
            render_json(context, segments_path)
            outputs["segments"] = str(segments_path)

        if self.options.write_quality:
            quality_path = self._quality_path(stem, total)
            payload = {
                "schema": "dsh-bilibili-subtitles/quality/v1",
                "generated_at": now_local_iso(),
                "video": video.to_dict(),
                "quality": quality,
                "parts": [
                    {
                        "part": p.part.to_dict(),
                        "subtitle": {
                            "source": p.track.source,
                            "language": p.track.language,
                            "confidence": p.track.confidence,
                            "meta": p.track.meta,
                            "segments": len(p.track.segments),
                            "paragraphs": len(p.paragraphs),
                        },
                        "attempts": p.attempts,
                        "quality": p.quality,
                    }
                    for p in part_results
                ],
                "render_errors": render_errors,
                "outputs": outputs,
            }
            ensure_dir(quality_path.parent)
            quality_path.write_text(json_dumps(payload), encoding="utf-8", newline="\n")
            outputs["quality"] = str(quality_path)

        result = VideoResult(
            video=video,
            parts=part_results,
            outputs=outputs,
            quality=quality,
        )
        return result

    # ------------------------------------------------------------------
    # One part
    # ------------------------------------------------------------------
    def _process_part(
        self,
        video: VideoInfo,
        part: VideoPart,
        item: InputItem,
        *,
        client: BilibiliClient | None,
        prefetched: SubtitleTrack | None = None,
    ) -> PartResult:
        attempts: list[dict] = []
        if prefetched is not None:
            tracks = [prefetched]
        else:
            tracks = self._acquire(
                video, part, item, client=client, attempts=attempts
            )
        primary = tracks[0]
        secondary = tracks[1] if len(tracks) > 1 else None

        drop_patterns = list(CleanOptions().drop_patterns)
        if self.options.drop_patterns:
            drop_patterns.extend(self.options.drop_patterns)
        clean_options = CleanOptions(
            merge_sentences=self.options.merge_sentences,
            drop_patterns=drop_patterns,
            glossary=self.glossary,
            bilingual=self.options.bilingual,
            primary_lang=canonical_lang(self.options.language) or primary.language,
            auto_punctuation=self.options.auto_punctuation,
        )
        cleaned, paragraphs = clean_track(primary, clean_options, secondary=secondary)
        expected = None if self.options.bilingual else self.options.language
        quality = analyze(
            cleaned,
            paragraphs,
            video_duration=part.duration or video.duration,
            expected_language=expected,
            extra_warnings=[
                a["message"] for a in attempts if a.get("status") == "warn" and a.get("message")
            ],
        )
        if self.options.bilingual and not any(p.translation for p in paragraphs):
            quality["warnings"].append("没有可用的双语对照文本。")
            if quality["status"] == "ok":
                quality["status"] = "warn"
        return PartResult(
            part=part,
            track=cleaned,
            paragraphs=paragraphs,
            quality=quality,
            attempts=attempts,
        )

    def _acquire(
        self,
        video: VideoInfo,
        part: VideoPart,
        item: InputItem,
        *,
        client: BilibiliClient | None,
        attempts: list[dict],
    ) -> list[SubtitleTrack]:
        options = self.options
        last_error: VSubError | None = None

        def run(name: str, func: Callable[[], object]) -> object | None:
            nonlocal last_error
            start = time.monotonic()
            try:
                value = func()
                attempts.append(_attempt(name, "ok", "", time.monotonic() - start))
                return value
            except VSubError as exc:
                last_error = exc
                attempts.append(_attempt(name, "failed", exc.message, time.monotonic() - start))
                if options.verbose:
                    self.log(f"    {name} 失败: {exc.message}")
                return None
            except Exception as exc:  # noqa: BLE001
                last_error = ProviderError(f"{name} 失败: {exc}")
                attempts.append(_attempt(name, "failed", str(exc), time.monotonic() - start))
                return None

        # 1. Explicit external subtitle (highest fidelity).
        if item.subtitle_path and (len(video.parts) == 1 or part is video.parts[0]):
            provider = ExternalSubtitleProvider(
                item.subtitle_path,
                language=options.language,
                hint=video.bvid or video.title,
            )
            track = run("external", provider.fetch)
            if track is not None:
                return [track]  # type: ignore[list-item]

        # 2. Platform or embedded source.
        if item.kind == "bilibili" and client is not None:
            provider = BilibiliSubtitleProvider(
                client,
                languages=[options.language] if options.language else [],
                bilingual=options.bilingual,
            )
            tracks = run("bilibili", lambda: provider.fetch_tracks(part))
            if tracks:
                return tracks  # type: ignore[return-value]
        elif item.kind == "video" and item.video_path:
            provider = EmbeddedSubtitleProvider(
                item.video_path,
                ffmpeg=options.ffmpeg,
                language=options.language,
                workdir=self._work_root / f"p{part.index}" if self._work_root else None,
            )
            track = run("embedded", provider.fetch)
            if track is not None:
                return [track]  # type: ignore[list-item]

        # 3. Hard-coded OCR (local video only).
        if options.ocr:
            if item.kind == "video" and item.video_path:
                provider = OCRSubtitleProvider(
                    item.video_path,
                    ffmpeg=options.ffmpeg,
                    language=options.language,
                    fps=options.ocr_fps,
                    crop_ratio=options.ocr_crop,
                    full_frame=options.ocr_full_frame,
                    min_confidence=options.ocr_min_confidence,
                    workdir=self._work_root / f"ocr_p{part.index}" if self._work_root else None,
                    logger=self.log if options.verbose else None,
                )
                track = run("ocr", provider.fetch)
                if track is not None:
                    return [track]  # type: ignore[list-item]
            else:
                attempts.append(_attempt("ocr", "skipped", "OCR 仅支持本地视频文件。"))

        # 4. ASR fallback.
        if options.asr is not False:
            provider = ASRSubtitleProvider(
                model_size=options.asr_model,
                language=options.asr_language or options.language,
                device=options.asr_device,
                compute_type=options.asr_compute_type,
                model_dir=options.model_dir,
                initial_prompt=self._asr_prompt(),
                logger=self.log,
            )
            available, reason = provider.available()
            if not available:
                attempts.append(_attempt("asr", "skipped", reason.splitlines()[0]))
            else:
                media_path: Path | str | None = None
                if item.kind == "video" and item.video_path:
                    media_path = item.video_path
                elif item.kind == "bilibili" and client is not None:
                    assert self._work_root is not None
                    audio = self._work_root / f"audio_p{part.index}.m4a"
                    try:
                        media_path = client.download_audio(
                            part,
                            audio,
                            progress=options.verbose,
                        )
                    except VSubError as exc:
                        last_error = exc
                        attempts.append(_attempt("asr", "failed", f"音频下载失败: {exc.message}"))
                if media_path:
                    track = run("asr", lambda: provider.fetch(media_path))  # type: ignore[arg-type]
                    if track is not None:
                        return [track]  # type: ignore[list-item]

        if last_error is None:
            last_error = NoSubtitleError("没有可用的字幕来源。")
        if isinstance(last_error, (LoginRequiredError, DependencyMissingError, ParseError)):
            raise last_error
        raise NoSubtitleError(
            last_error.message if last_error else "没有可用的字幕来源。",
            hint=last_error.hint if last_error else None,
            detail={"attempts": attempts},
        )

    def _asr_prompt(self) -> str | None:
        if not self.glossary:
            return None
        terms = list(self.glossary.mapping.keys())[:40]
        return "术语：" + "、".join(terms) if terms else None

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------
    def _unique_stem(self, base: str) -> str:
        stem = base or "video"
        candidate = stem
        i = 2
        while candidate.lower() in self._used_stems:
            candidate = f"{stem}_{i}"
            i += 1
        self._used_stems.add(candidate.lower())
        return candidate

    def _quality_path(self, stem: str, total: int) -> Path:
        if self.options.quality_path:
            p = Path(self.options.quality_path)
            if total > 1:
                ensure_dir(p)
                return p / f"{stem}.quality.json"
            if p.suffix.lower() == ".json":
                return p
            ensure_dir(p)
            return p / f"{stem}.quality.json"
        return self.out_dir / f"{stem}.quality.json"

    def _write_error(self, item: InputItem, error: dict) -> None:
        hint = (item.hint or item.raw or "input").split("?", 1)[0]
        base = safe_filename(hint, max_len=60)
        path = self.out_dir / f"{base}.error.json"
        i = 2
        while path.exists():
            path = self.out_dir / f"{base}_{i}.error.json"
            i += 1
        try:
            path.write_text(json_dumps(error), encoding="utf-8", newline="\n")
        except OSError:
            # The original error is already logged; never mask it with a
            # secondary failure to write the diagnostic file.
            pass

    def _write_manifest(self, results: list[VideoResult], errors: list[dict]) -> Path | None:
        if not results and not errors:
            return None
        payload = {
            "schema": "dsh-bilibili-subtitles/manifest/v1",
            "generated_at": now_local_iso(),
            "out_dir": str(self.out_dir),
            "results": [
                {
                    "input": r.video.input,
                    "title": r.video.title,
                    "bvid": r.video.bvid,
                    "parts": len(r.parts),
                    "status": r.quality.get("status"),
                    "score": r.quality.get("score"),
                    "outputs": r.outputs,
                }
                for r in results
            ],
            "errors": errors,
        }
        path = self.out_dir / "_manifest.json"
        try:
            path.write_text(json_dumps(payload), encoding="utf-8", newline="\n")
        except OSError:
            return None
        return path

    def _cleanup(self) -> None:
        if self._work_root and self._owns_work_root and not self.options.keep_temp:
            shutil.rmtree(self._work_root, ignore_errors=True)


def _safe_detail(detail: object) -> object:
    if detail is None:
        return None
    try:
        json.dumps(detail)
        return detail
    except TypeError:
        return str(detail)


__all__ = ["Pipeline", "PipelineOptions", "RunResult"]
