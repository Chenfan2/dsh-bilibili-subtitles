"""A tiny local Bilibili API stand-in for end-to-end tests (no network)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SUBTITLE_BODY = {
    "font_size": 0.4,
    "body": [
        {"from": 0.0, "to": 3.0, "location": 2, "text": "这是第一句测试字幕。"},
        {"from": 3.2, "to": 6.0, "location": 2, "text": "第二句用来检查时间轴和段落。"},
        {"from": 6.2, "to": 9.0, "location": 2, "text": "第三句包含一个产品名：DeepSeek。"},
        {"from": 9.2, "to": 12.0, "location": 2, "text": "最后一句，谢谢观看。"},
    ],
}

SUBTITLE_BODY_EN = {
    "font_size": 0.4,
    "body": [
        {"from": 0.0, "to": 3.0, "location": 2, "text": "This is the first test caption."},
        {"from": 3.2, "to": 6.0, "location": 2, "text": "The second checks timing and paragraphs."},
        {"from": 6.2, "to": 9.0, "location": 2, "text": "The third mentions DeepSeek."},
        {"from": 9.2, "to": 12.0, "location": 2, "text": "The last one says thanks for watching."},
    ],
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockBilibili/1.0"

    def log_message(self, fmt, *args):  # silence test output
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        port = self.server.server_address[1]
        if path == "/x/web-interface/view":
            pages = [{"cid": 789012, "page": 1, "part": "正片", "duration": 95}]
            if getattr(self.server, "multi_pages", False):
                pages.append({"cid": 789013, "page": 2, "part": "第二P", "duration": 95})
            self._json(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "bvid": "BV1xx411c7mD",
                        "aid": 123456,
                        "cid": 789012,
                        "title": "测试视频：AI 与研究工作流",
                        "desc": "仅用于 pipeline 测试的模拟视频。",
                        "duration": 190 if len(pages) > 1 else 95,
                        "pubdate": 1700000000,
                        "owner": {"name": "测试UP", "mid": 42},
                        "pic": "",
                        "pages": pages,
                    },
                }
            )
            return
        if path == "/x/player/v2":
            subtitles = []
            if not getattr(self.server, "empty_subtitles", False):
                subtitles = [
                    {
                        "lan": "ai-zh",
                        "lan_doc": "中文（AI生成）",
                        "subtitle_url": f"http://127.0.0.1:{port}/subtitle.json",
                        "ai_type": 1,
                        "is_lock": False,
                        "author": {"name": "AI"},
                    }
                ]
                if getattr(self.server, "dual_subtitles", False):
                    subtitles.append(
                        {
                            "lan": "en-US",
                            "lan_doc": "English (AI)",
                            "subtitle_url": f"http://127.0.0.1:{port}/subtitle_en.json",
                            "ai_type": 1,
                            "is_lock": False,
                            "author": {"name": "AI"},
                        }
                    )
            self._json(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {"subtitle": {"subtitles": subtitles}},
                }
            )
            return
        if path == "/subtitle.json":
            self._json(SUBTITLE_BODY)
            return
        if path == "/subtitle_en.json":
            self._json(SUBTITLE_BODY_EN)
            return
        if path == "/x/player/playurl":
            self._json({"code": 0, "data": {"dash": {"audio": []}}})
            return
        self._json({"code": -404, "message": "not found"}, status=404)


class MockBilibiliServer:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
