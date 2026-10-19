# dsh-bilibili-subtitles

把 Bilibili 视频（或本地视频/字幕）变成可读、可检索、可交付的字幕文档。优先使用平台/外挂字幕，Whisper 语音转写和硬字幕 OCR 只做兜底。

## 功能

- Bilibili 链接：BV/av、分P、番剧 ep/ss、b23.tv 短链。
- 字幕来源：外挂 SRT/VTT/ASS/Bilibili JSON → 平台/CC/AI 字幕 → 本地内嵌字幕 → 硬字幕 OCR → Whisper ASR。
- 文档格式：Markdown、Word（.docx）、PDF、TXT、SRT、结构化 JSON。
- 清洗：去重、广告/水印过滤、短句合并、按语义/停顿分段、术语表、说话人标记。
- 双语：两条字幕轨按时间对齐；单轨双行字幕自动拆分。
- 质量报告：覆盖率、重叠、低置信度、乱码、语速异常、前/中/尾抽样。
- 批量目录、失败降级、错误报告、manifest。

## 环境

- Python 3.10+
- 核心只依赖标准库；DOCX 需要 `python-docx`。
- 可选：
  - ASR：`faster-whisper`（首次使用会下载模型）
  - PDF：LibreOffice，或 `reportlab`
  - OCR：`rapidocr_onnxruntime` + ffmpeg
  - 内嵌字幕/抽帧：ffmpeg（也可用 `imageio-ffmpeg` 提供二进制）

```bash
pip install -r requirements.txt
# 可选
pip install faster-whisper reportlab imageio-ffmpeg rapidocr_onnxruntime
```

在 DSH 环境中，优先使用 `load_workspace_dependencies` 返回的 Python；它自带 `python-docx`。若要启用 ASR/PDF，可把可选依赖安装到工作区目录，并通过 `PYTHONPATH` 引入。

## 快速开始

```bash
# 平台字幕 → Markdown + Word
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx

# 指定输出
python main.py "BV1xx411c7mD" --format docx -o "笔记.docx"

# 本地视频 + 外挂字幕
python main.py input.mp4 --subtitle input.srt --format md,docx

# 批量目录
python main.py ./videos --format md,docx --out-dir output/batch
```

输出目录默认 `output/`，每个视频会生成：

```text
<标题>_<BV号>.md
<标题>_<BV号>.docx
<标题>_<BV号>.quality.json
<标题>_<BV号>.segments.json
_manifest.json
```

## Bilibili 登录（平台字幕必需）

B 站只在登录会话下返回平台/AI 字幕的 `subtitle_url`。推荐用环境变量：

```powershell
$env:BILIBILI_SESSDATA = "你的 SESSDATA"
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx
```

获取：浏览器登录 bilibili.com → 开发者工具 → Application → Cookies → `bilibili.com` → 复制 `SESSDATA`。

也支持 `--sessdata`、`--cookie "SESSDATA=...; bili_jct=..."`、`--cookies cookies.txt`。

> Cookie 是账号凭证，不要提交到仓库或发给他人。本工具不会把 Cookie 写进日志/质量报告。

没有 Cookie 时：

- 平台字幕会报 `LOGIN_REQUIRED`（这是 B 站限制）。
- 如果安装了 `faster-whisper`，可以加 `--asr` 用语音转写兜底。
- 也可以自己提供外挂字幕 `--subtitle`，质量最好。

## 常用参数

```text
--format md,docx,pdf,txt,srt,json   输出格式
--bilingual                          双语对照
--timestamps / --no-timestamps       正文时间戳（默认显示）
--merge-sentences                    合并被切开的短句（默认开启）
--no-auto-punctuation                关闭 ASR/OCR 自动补标点
--title TEXT                         覆盖文档标题
--pages auto/all/1,3-5               分P选择
--subtitle PATH                      外挂字幕文件/目录
--language zh                        首选语言
--template default/minimal/FILE.md   Markdown 模板
--quality-report PATH                质量报告路径
--glossary terms.json                术语替换
--asr / --no-asr                     ASR 兜底开关
--asr-model small                    Whisper 模型
--model-dir DIR                      模型缓存目录（默认 ./.vsub-models-cache）
--ocr                                硬字幕 OCR（本地视频）
--ffmpeg PATH                        指定 ffmpeg
--json-summary                       stdout 输出机器可读摘要
```

完整帮助：`python main.py --help`。

## 质量报告

```json
{
  "status": "ok",
  "score": 96.5,
  "source": "bilibili",
  "language": "zh",
  "segments": 320,
  "paragraphs": 86,
  "duration": 1260.0,
  "duration_covered": 0.96,
  "coverage_span": 0.99,
  "overlaps": 0,
  "low_confidence_segments": 3,
  "warnings": [],
  "samples": {"head": [], "middle": [], "tail": []}
}
```

- `duration_covered` 以完整视频时长为分母；清理片头/片尾广告后会偏低。
- `coverage_span` 以首尾字幕之间为分母，更能反映正文覆盖。
- `status`：`ok` / `warn` / `fail`；失败时不会假装成功。

## 失败与降级

1. 外挂字幕解析失败 → 继续平台/内嵌字幕。
2. 平台字幕需要登录 → 提示 `SESSDATA`；已安装 Whisper 且允许 ASR 时自动兜底。
3. 没有字幕轨 → `NO_SUBTITLE`；建议外挂字幕或 `--asr`。
4. 内嵌字幕是 PGS/VobSub 位图 → 无法转 SRT，建议 OCR/外挂。
5. ASR 未安装 → 明确提示安装命令，不静默失败。
6. 某个输出格式失败 → 其他格式继续；全部失败才报 `RENDER_FAILED`。
7. 批量中单个失败 → 成功项继续，`_manifest.json` 与 `*.error.json` 记录。

退出码：`0` 成功，`2` 输入/API/解析，`3` 无字幕/需登录/质量失败，`4` 缺少依赖，`5` 渲染失败，`1` 未预期错误。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- SRT/VTT/ASS/Bilibili JSON/纯文本解析。
- 清洗、去重、广告过滤、短句合并、双语、术语。
- 覆盖率/重叠/低置信度/聚合质量报告。
- Markdown/Word/SRT/JSON 渲染。
- 本地 mock Bilibili API 的端到端流程（不联网）。
- 登录缺失时的错误路径。

## 项目结构

```text
dsh-bilibili-subtitles/
├── SKILL.md
├── README.md
├── main.py
├── vsub/
│   ├── bilibili.py
│   ├── input_adapter.py
│   ├── pipeline.py
│   ├── quality.py
│   ├── providers/
│   │   ├── external.py
│   │   ├── bilibili.py
│   │   ├── embedded.py
│   │   ├── ocr.py
│   │   └── asr.py
│   ├── parsers/
│   ├── cleaners/
│   └── renderers/
├── templates/
├── tests/
├── requirements.txt
└── install.ps1
```

## 局限

- 平台字幕可用性取决于视频、账号、地区、UP 主设置，无法绕过权限。
- AI 字幕可能错字、漏句、时间轴漂移；质量报告只提示，不替代人工校对。
- 双语是时间对齐，不是翻译。
- 自动说话人分离未实现；保留字幕中的 `[说话人]` 标记。
- OCR 仅本地视频，默认底部 30%，实验性。
- PDF 需要 LibreOffice 或 reportlab；没有时会明确报错。
- 长视频 ASR 较慢；`small` 模型首次下载约 460MB。

## 版权与隐私

仅处理你有权使用的视频/字幕。字幕文档会保留原视频标题、UP 主和链接以便溯源。Cookie、签名 CDN URL 不会写入日志/报告。临时音频/抽帧默认位于输出目录的 `.vsub-tmp`，运行结束自动清理。
