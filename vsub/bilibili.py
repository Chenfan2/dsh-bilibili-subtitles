"""Bilibili URL resolution, subtitle listing/download and audio extraction."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlencode, urlparse

from .errors import BilibiliError, LoginRequiredError, NoSubtitleError, UnsupportedInputError
from .http import HttpClient, is_bilibili_host
from .models import SubtitleTrack, VideoInfo, VideoPart
from .parsers import parse_bilibili_json
from .utils import canonical_lang, parse_page_selection, redact_url, timestamp_to_date

API_BASE = "https://api.bilibili.com"
WWW_BASE = "https://www.bilibili.com"

_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_AV_RE = re.compile(r"av(\d+)", re.I)
_EP_RE = re.compile(r"ep(\d+)", re.I)
_SS_RE = re.compile(r"ss(\d+)", re.I)


@dataclass(slots=True)
class ParsedLink:
    kind: str  # video | short | bangumi_ep | bangumi_ss
    raw: str
    bvid: str | None = None
    aid: int | None = None
    ep_id: int | None = None
    season_id: int | None = None
    page: int | None = None


def parse_bilibili_link(text: str) -> ParsedLink:
    """Accept BV/av ids, full video URLs, b23.tv short links and bangumi URLs."""
    raw = (text or "").strip()
    if not raw:
        raise UnsupportedInputError("输入为空。")

    # Plain ids copied from the app.
    if _BV_RE.fullmatch(raw):
        return ParsedLink("video", raw, bvid=raw)
    if re.fullmatch(r"av\d+", raw, re.I):
        return ParsedLink("video", raw, aid=int(raw[2:]))

    # Pull a URL out of surrounding share text.
    url_match = re.search(r"https?://[^\s【】<>\"']+", raw)
    if url_match:
        raw = url_match.group(0)
    elif re.match(r"^(www\.|b23\.tv|bili2233\.cn)", raw, re.I):
        raw = "https://" + raw

    if not re.match(r"^https?://", raw, re.I):
        if _BV_RE.search(raw):
            return ParsedLink("video", raw, bvid=_BV_RE.search(raw).group(0))
        raise UnsupportedInputError(f"无法识别的 Bilibili 链接: {text!r}")

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host in {"b23.tv", "bili2233.cn"} or host.endswith(".b23.tv"):
        return ParsedLink("short", raw)
    if not is_bilibili_host(raw):
        raise UnsupportedInputError(f"不是 Bilibili 链接: {raw}")

    path = parsed.path or ""
    qs = parse_qs(parsed.query)
    page = None
    for key in ("p", "page"):
        if key in qs:
            try:
                page = int(qs[key][0])
            except (ValueError, IndexError):
                page = None
            break

    m = _BV_RE.search(path) or _BV_RE.search(raw)
    m_av = _AV_RE.search(path) or _AV_RE.search(raw)
    if m or m_av:
        return ParsedLink(
            "video",
            raw,
            bvid=m.group(0) if m else None,
            aid=int(m_av.group(1)) if m_av else None,
            page=page,
        )

    m_ep = _EP_RE.search(path)
    if m_ep:
        return ParsedLink("bangumi_ep", raw, ep_id=int(m_ep.group(1)))
    m_ss = _SS_RE.search(path)
    if m_ss:
        return ParsedLink("bangumi_ss", raw, season_id=int(m_ss.group(1)))

    raise UnsupportedInputError(
        f"暂不支持该 Bilibili 链接类型: {raw}",
        hint="支持 /video/BV...、/video/av...、/bangumi/play/ep...、/bangumi/play/ss... 和 b23.tv 短链。",
    )


class BilibiliClient:
    def __init__(
        self,
        *,
        cookie: str | None = None,
        cookies_file: str | None = None,
        timeout: float = 25.0,
        retries: int = 3,
        delay: float = 0.4,
        api_base: str = API_BASE,
        warmup: bool = False,
        logger: Callable[[str], None] | None = None,
    ):
        self.http = HttpClient(cookie=cookie, timeout=timeout, retries=retries, delay=delay)
        if cookies_file:
            self.http.load_cookies_file(cookies_file)
        self.api_base = api_base.rstrip("/")
        self.log = logger or (lambda _msg: None)
        if warmup:
            self.http.warmup(WWW_BASE)

    # ------------------------------------------------------------------
    # Low-level API
    # ------------------------------------------------------------------
    def _api(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.api_base}{path}"
        data = self.http.get_json(url, params=params)
        if not isinstance(data, dict):
            raise BilibiliError(f"Bilibili API 返回了意外数据: {path}")
        return data

    def _check(self, data: dict, context: str) -> dict:
        code = data.get("code", 0)
        if code == 0:
            return data.get("data") or {}
        message = data.get("message") or data.get("msg") or "未知错误"
        hints = {
            -101: "Cookie 未登录或已失效，请更新 SESSDATA。",
            -352: "B 站风控拦截，稍后重试、降低请求频率，或提供有效 Cookie。",
            -403: "访问被拒绝，Cookie 可能已过期。",
            -404: "视频不存在或已被删除。",
            62002: "稿件不可见（可能仅 UP 主可见）。",
            62004: "稿件正在审核中。",
        }
        raise BilibiliError(
            f"{context}失败（code={code}）: {message}",
            hint=hints.get(code),
            detail={"code": code, "message": message},
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(
        self,
        link_text: str,
        *,
        pages: str | None = "auto",
        max_episodes: int = 50,
    ) -> VideoInfo:
        parsed = parse_bilibili_link(link_text)
        if parsed.kind == "short":
            final = self.http.resolve_redirect(parsed.raw)
            self.log(f"短链解析: {parsed.raw} -> {final}")
            parsed = parse_bilibili_link(final)

        if parsed.kind == "video":
            return self._resolve_video(parsed, pages=pages)
        if parsed.kind in {"bangumi_ep", "bangumi_ss"}:
            return self._resolve_bangumi(parsed, pages=pages, max_episodes=max_episodes)
        raise UnsupportedInputError(f"无法解析链接: {link_text}")

    def _resolve_video(self, parsed: ParsedLink, *, pages: str | None) -> VideoInfo:
        params: dict[str, Any] = {}
        if parsed.bvid:
            params["bvid"] = parsed.bvid
        elif parsed.aid:
            params["aid"] = parsed.aid
        else:
            raise UnsupportedInputError("链接中没有 BV/av 号。")
        data = self._check(self._api("/x/web-interface/view", params), "获取视频信息")

        all_pages = data.get("pages") or []
        if not all_pages:
            all_pages = [{"cid": data.get("cid"), "page": 1, "part": data.get("title", ""), "duration": data.get("duration", 0)}]

        total = len(all_pages)
        if pages and pages.lower() == "all":
            selected = list(range(total))
        elif pages and pages.lower() not in {"auto", "default"}:
            selected = parse_page_selection(pages, total)
        elif parsed.page:
            selected = [min(max(parsed.page - 1, 0), total - 1)]
        else:
            selected = [0]

        bvid = data.get("bvid") or parsed.bvid
        title = data.get("title") or bvid or "Bilibili 视频"
        pubdate = timestamp_to_date(data.get("pubdate"))
        parts: list[VideoPart] = []
        for idx in selected:
            page = all_pages[idx]
            pno = int(page.get("page") or idx + 1)
            part_title = (page.get("part") or "").strip()
            if total == 1 and part_title == title:
                part_title = None
            parts.append(
                VideoPart(
                    index=pno,
                    title=title,
                    part_title=part_title or None,
                    bvid=bvid,
                    aid=data.get("aid"),
                    cid=page.get("cid"),
                    duration=float(page.get("duration") or data.get("duration") or 0),
                    url=f"{WWW_BASE}/video/{bvid}?p={pno}" if bvid else parsed.raw,
                    cover=data.get("pic"),
                    pubdate=pubdate,
                )
            )

        return VideoInfo(
            input=parsed.raw,
            platform="bilibili",
            title=title,
            url=f"{WWW_BASE}/video/{bvid}" if bvid else parsed.raw,
            owner=(data.get("owner") or {}).get("name"),
            owner_mid=(data.get("owner") or {}).get("mid"),
            desc=data.get("desc"),
            cover=data.get("pic"),
            pubdate=pubdate,
            # Sum the selected parts, not the whole multi-P video. Selecting
            # P2 only must not make the P1/P2 total the QA denominator.
            duration=sum(p.duration for p in parts) or float(data.get("duration") or 0),
            bvid=bvid,
            aid=data.get("aid"),
            parts=parts,
            extra={"page_count": total, "selected_pages": [p.index for p in parts]},
        )

    def _resolve_bangumi(self, parsed: ParsedLink, *, pages: str | None, max_episodes: int) -> VideoInfo:
        params: dict[str, Any] = {}
        if parsed.ep_id:
            params["ep_id"] = parsed.ep_id
        elif parsed.season_id:
            params["season_id"] = parsed.season_id
        raw = self._api("/pgc/view/web/season", params)
        if raw.get("code") not in (0, None):
            self._check(raw, "获取番剧信息")
        # PGC responses use {"result": ...}, unlike the normal {"data": ...}.
        result = raw.get("result") or raw.get("data") or {}
        episodes = result.get("episodes") or []
        if not episodes:
            raise BilibiliError("番剧没有可用的剧集。")

        if parsed.kind == "bangumi_ep" and parsed.ep_id:
            chosen = [ep for ep in episodes if int(ep.get("id") or ep.get("ep_id") or 0) == parsed.ep_id]
            if not chosen:
                chosen = episodes[:1]
        else:
            chosen = episodes
            if max_episodes and len(chosen) > max_episodes:
                self.log(f"番剧共 {len(chosen)} 集，只处理前 {max_episodes} 集（--max-episodes）。")
                chosen = chosen[:max_episodes]

        if pages and pages.lower() not in {"auto", "default", "all"}:
            idxs = parse_page_selection(pages, len(chosen))
            chosen = [chosen[i] for i in idxs]
        elif pages and pages.lower() == "all":
            pass

        season_title = result.get("season_title") or result.get("title") or "Bilibili 番剧"
        season_id = result.get("season_id") or parsed.season_id
        up_info = result.get("up_info") or {}
        parts: list[VideoPart] = []
        for i, ep in enumerate(chosen, start=1):
            ep_id = ep.get("id") or ep.get("ep_id")
            ep_title = (ep.get("title") or "").strip()
            long_title = (ep.get("long_title") or "").strip()
            part_title = " ".join(x for x in (ep_title, long_title) if x) or f"第 {i} 集"
            duration = float(ep.get("duration") or 0)
            if duration > 100_000:  # PGC returns milliseconds, normal videos seconds
                duration /= 1000.0
            bvid = ep.get("bvid")
            parts.append(
                VideoPart(
                    index=i,
                    title=season_title,
                    part_title=part_title,
                    bvid=bvid,
                    aid=ep.get("aid"),
                    cid=ep.get("cid"),
                    ep_id=int(ep_id) if ep_id else None,
                    duration=duration,
                    url=f"{WWW_BASE}/bangumi/play/ep{ep_id}" if ep_id else parsed.raw,
                    cover=ep.get("cover") or result.get("cover"),
                    pubdate=timestamp_to_date(ep.get("pub_time")) or (result.get("publish") or {}).get("pub_time"),
                )
            )

        return VideoInfo(
            input=parsed.raw,
            platform="bilibili",
            title=season_title,
            url=parsed.raw,
            owner=up_info.get("uname"),
            owner_mid=up_info.get("mid"),
            desc=result.get("evaluate"),
            cover=result.get("cover"),
            pubdate=(result.get("publish") or {}).get("pub_time"),
            duration=sum(p.duration for p in parts),
            bvid=parts[0].bvid if parts else None,
            season_id=season_id,
            parts=parts,
            extra={"episode_count": len(episodes), "selected_episodes": len(parts)},
        )

    # ------------------------------------------------------------------
    # Subtitle listing / download
    # ------------------------------------------------------------------
    def _player_params(self, part: VideoPart) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if part.bvid:
            params["bvid"] = part.bvid
        elif part.ep_id:
            params["ep_id"] = part.ep_id
        if part.cid:
            params["cid"] = part.cid
        return params

    def list_subtitles(self, part: VideoPart) -> list[dict]:
        params = self._player_params(part)
        if not params:
            raise BilibiliError("缺少 bvid/ep_id/cid，无法读取字幕列表。")
        data = self._api("/x/player/v2", params)
        if data.get("code") == -101:
            raise LoginRequiredError("读取字幕列表需要登录（code=-101）。")
        if data.get("code") not in (0, None):
            # Some deployments require WBI signing for this endpoint.
            data = self._api("/x/player/wbi/v2", self._wbi_sign(params))
        if data.get("code") not in (0, None):
            self._check(data, "读取字幕列表")
        player = data.get("data") or {}
        subtitle = player.get("subtitle") or {}
        tracks = subtitle.get("subtitles") or []
        tracks = [t for t in tracks if isinstance(t, dict)]
        if tracks:
            return tracks

        # Empty list is ambiguous. Anonymous Bilibili sessions usually hide
        # platform/AI subtitles entirely, so treat that as a login hint.
        if not self.http.has_cookie("SESSDATA"):
            raise LoginRequiredError(
                "未登录时 Bilibili 不返回字幕列表（或该视频确实没有字幕）。",
                hint="提供 SESSDATA 后再试；也可以加 --asr 用语音转写兜底（需安装 faster-whisper）。",
            )
        raise NoSubtitleError("该视频没有可用字幕轨（UP 主未上传，也未生成 AI 字幕）。")

    def fetch_subtitle_tracks(
        self,
        part: VideoPart,
        *,
        languages: Iterable[str] | None = None,
        bilingual: bool = False,
    ) -> list[SubtitleTrack]:
        available = self.list_subtitles(part)
        selected = self._select_tracks(available, languages=languages or (), bilingual=bilingual)
        if not selected:
            raise NoSubtitleError("字幕列表为空或没有匹配的语言。")

        tracks: list[SubtitleTrack] = []
        for item in selected:
            url = (item.get("subtitle_url") or "").strip()
            if url.startswith("//"):
                url = "https:" + url
            if not url:
                continue
            self.log(
                f"下载字幕: {item.get('lan_doc') or item.get('lan')} "
                f"({redact_url(url)})"
            )
            try:
                data = self.http.get_json(
                    url,
                    headers={"Referer": f"{WWW_BASE}/", "Origin": WWW_BASE},
                )
            except Exception as exc:  # noqa: BLE001
                raise BilibiliError(
                    f"字幕文件下载失败: {exc}",
                    hint="字幕 CDN 链接可能已过期，请重试或更换网络。",
                ) from exc
            meta = {
                "lan": item.get("lan"),
                "lan_doc": item.get("lan_doc"),
                "ai_type": item.get("ai_type"),
                "is_ai": bool(item.get("ai_type")) or "ai" in str(item.get("lan", "")).lower(),
                "author": (item.get("author") or {}).get("name"),
                "url": redact_url(url),
            }
            track = parse_bilibili_json(
                data,
                language=item.get("lan"),
                source="bilibili",
                meta=meta,
            )
            if track.segments:
                tracks.append(track)
        if not tracks:
            raise NoSubtitleError("字幕轨存在，但内容为空或全部下载失败。")
        return tracks

    def _select_tracks(
        self,
        available: list[dict],
        *,
        languages: Iterable[str],
        bilingual: bool,
    ) -> list[dict]:
        prefs = [str(x).strip() for x in languages if str(x).strip()]
        if not prefs:
            prefs = ["zh-Hans", "zh-CN", "ai-zh", "zh", "en-US", "ai-en", "en"]

        def score(item: dict) -> int:
            lan = str(item.get("lan") or "")
            doc = str(item.get("lan_doc") or "")
            best = -1
            for i, pref in enumerate(prefs):
                weight = (len(prefs) - i) * 2
                if lan.lower() == pref.lower():
                    best = max(best, 1000 + weight)
                elif lan.lower().startswith(pref.lower()):
                    best = max(best, 700 + weight)
                elif canonical_lang(lan) == canonical_lang(pref):
                    best = max(best, 500 + weight)
                elif pref.lower() in doc.lower():
                    best = max(best, 300 + weight)
            if item.get("subtitle_url"):
                best += 20
            return best

        ranked = sorted(available, key=score, reverse=True)
        primary = ranked[0]
        if not bilingual:
            return [primary]

        primary_lang = canonical_lang(primary.get("lan"))
        secondary = next(
            (
                item
                for item in ranked[1:]
                if canonical_lang(item.get("lan")) != primary_lang
            ),
            None,
        )
        if secondary is None:
            self.log("警告: 只有一种语言的字幕，无法生成双语对照。")
            return [primary]
        return [primary, secondary]

    # ------------------------------------------------------------------
    # WBI signing (fallback when /x/player/v2 is rejected)
    # ------------------------------------------------------------------
    _MIXIN_KEY_ENC_TAB = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
        27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
    ]

    def _wbi_keys(self) -> tuple[str, str] | None:
        try:
            data = self._api("/x/web-interface/nav")
            wbi = (data.get("data") or {}).get("wbi_img") or {}
            img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
            sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
            if img and sub:
                return img, sub
        except Exception:
            pass
        return None

    def _wbi_sign(self, params: dict[str, Any]) -> dict[str, Any]:
        keys = self._wbi_keys()
        if not keys:
            return params
        img_key, sub_key = keys
        raw = img_key + sub_key
        mixin = "".join(raw[i] for i in self._MIXIN_KEY_ENC_TAB if i < len(raw))[:32]
        signed = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
        signed["wts"] = int(time.time())
        signed = dict(sorted(signed.items()))
        query = urlencode(signed)
        signed["w_rid"] = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
        return signed

    # ------------------------------------------------------------------
    # Audio for ASR fallback
    # ------------------------------------------------------------------
    def get_audio_url(self, part: VideoPart) -> str:
        params = self._player_params(part)
        params.update({"fnval": 16, "fnver": 0, "fourk": 1})
        data = self._check(self._api("/x/player/playurl", params), "获取音频流")
        dash = data.get("dash") or {}
        audios = dash.get("audio") or []
        if audios:
            best = max(audios, key=lambda a: int(a.get("bandwidth") or 0))
            url = best.get("baseUrl") or best.get("base_url") or best.get("baseURL")
            if url:
                return url
        durl = data.get("durl") or []
        if durl:
            url = durl[0].get("url")
            if url:
                return url
        raise BilibiliError("该视频没有可下载的音频流。", hint="可能需要登录 Cookie 或大会员权限。")

    def download_audio(self, part: VideoPart, dest: str | Path, *, progress: bool = True) -> Path:
        url = self.get_audio_url(part)
        suffix = ".flv" if ".flv" in url.lower() else ".m4a"
        dest = Path(dest).with_suffix(suffix)
        self.log(f"下载音频: {redact_url(url)}")
        return self.http.download(
            url,
            dest,
            headers={"Referer": f"{WWW_BASE}/", "Origin": WWW_BASE},
            progress=progress,
        )
