"""Tiny HTTP client built on the standard library.

The skill intentionally does not require ``requests`` so it can run inside the
bundled DSH Python.  It supports cookies (SESSDATA), gzip, retries and signed
CDN downloads.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from .utils import ensure_dir, format_size

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: bytes = b"", message: str = ""):
        self.status = status
        self.url = url
        self.body = body
        self.message = message or f"HTTP {status}"
        super().__init__(self.message)


class HttpClient:
    def __init__(
        self,
        *,
        cookie: str | None = None,
        timeout: float = 25.0,
        retries: int = 3,
        delay: float = 0.35,
        referer: str = "https://www.bilibili.com/",
        user_agent: str = DEFAULT_UA,
    ):
        self.timeout = timeout
        self.retries = max(0, retries)
        self.delay = max(0.0, delay)
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip",
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
        }
        self._last_request = 0.0
        if cookie:
            self.set_cookie_string(cookie)

    # -- cookies ---------------------------------------------------------
    def set_cookie(self, name: str, value: str, domain: str = ".bilibili.com") -> None:
        cookie = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path="/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        self.jar.set_cookie(cookie)

    def set_cookie_string(self, raw: str) -> None:
        raw = raw.strip()
        if raw.lower().startswith("cookie:"):
            raw = raw[7:].strip()
        for part in raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            name, value = name.strip(), value.strip().strip('"')
            if name:
                self.set_cookie(name, value)

    def load_cookies_file(self, path: str | Path) -> None:
        """Load Netscape cookies.txt or a JSON cookie export."""
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        stripped = text.lstrip()
        if stripped.startswith(("[", "{")):
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("cookies", [])
            for item in items:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                self.set_cookie(
                    str(item["name"]),
                    str(item.get("value", "")),
                    str(item.get("domain") or ".bilibili.com"),
                )
            return
        for line in text.splitlines():
            line = line.strip()
            if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            fields = line.split("\t")
            if len(fields) < 7:
                continue
            domain, _flag, _path, _secure, _expiry, name, value = fields[:7]
            self.set_cookie(name, value, domain)

    def has_cookie(self, name: str) -> bool:
        return any(c.name == name for c in self.jar)

    # -- core request ----------------------------------------------------
    def _throttle(self) -> None:
        if self.delay:
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        self._last_request = time.monotonic()

    def request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        data: bytes | None = None,
        retries: int | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params, doseq=True)
        retries = self.retries if retries is None else retries
        merged = dict(self.headers)
        if headers:
            merged.update(headers)

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            self._throttle()
            req = urllib.request.Request(url, data=data, headers=merged, method=method)
            try:
                with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        body = gzip.decompress(body)
                    return resp.status, body, dict(resp.headers)
            except urllib.error.HTTPError as exc:
                body = exc.read()
                last_error = HttpError(exc.code, url, body)
                if exc.code in {408, 412, 425, 429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise last_error from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(min(8.0, 1.2 * (2**attempt)))
                    continue
                raise

        raise last_error or RuntimeError("request failed")

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
        timeout: float | None = None,
    ) -> dict:
        _, body, _ = self.request(
            url, params=params, headers=headers, retries=retries, timeout=timeout
        )
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            snippet = body[:200].decode("utf-8", errors="replace")
            raise ValueError(f"响应不是合法 JSON: {snippet!r}") from exc

    def download(
        self,
        url: str,
        dest: str | Path,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        progress: bool = False,
    ) -> Path:
        dest = Path(dest)
        ensure_dir(dest.parent)
        merged = dict(self.headers)
        merged.pop("Accept", None)
        merged["Accept"] = "*/*"
        if headers:
            merged.update(headers)
        self._throttle()
        req = urllib.request.Request(url, headers=merged)
        with self.opener.open(req, timeout=timeout or max(self.timeout, 60)) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        pct = done * 100 / total
                        print(f"\r  下载中 {pct:5.1f}%  {format_size(done)}/{format_size(total)}", end="", flush=True)
            if progress:
                print()
        return dest

    def resolve_redirect(self, url: str) -> str:
        """Follow short-link redirects and return the final URL."""
        last_error: Exception | None = None
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, headers=self.headers, method=method)
                with self.opener.open(req, timeout=self.timeout) as resp:
                    return resp.geturl()
            except urllib.error.HTTPError as exc:
                if exc.code in {403, 405} and method == "HEAD":
                    continue
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - fall back to GET
                last_error = exc
        if last_error:
            raise last_error
        return url

    def warmup(self, url: str = "https://www.bilibili.com/") -> None:
        try:
            self.request(url, headers={"Accept": "text/html"}, timeout=15)
        except Exception:
            pass


def is_bilibili_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bilibili.com" or host.endswith(".bilibili.com") or host in {"b23.tv", "bili2233.cn"}
