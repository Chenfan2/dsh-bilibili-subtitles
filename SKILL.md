---
name: dsh-bilibili-subtitles
display-name: B站字幕转文档
description: 当用户需要从 Bilibili 视频链接（BV/av/ep/ss、b23.tv 短链）或本地视频中提取字幕，并整理成 Markdown/Word/PDF/TXT/SRT 文档时使用；优先使用平台/外挂字幕，ASR/OCR 仅作兜底。
version: 0.2.0
---

# dsh-bilibili-subtitles

把一条 Bilibili 视频链接变成可读、可检索、可交付的字幕文档。

核心原则：**先取现成字幕，再考虑语音转写或 OCR**。不要一上来就下载视频/音频做 Whisper；B 站平台字幕（含 AI 字幕）质量通常更好，也更快。

## 何时使用

适用：

- 用户给出 Bilibili 视频链接、BV 号、av 号、番剧 ep/ss 链接或 b23.tv 短链，要求“提取字幕/整理成文稿/导出 Word/Markdown”。
- 用户有本地视频 + 外挂字幕，想批量转成文档。
- 用户需要带时间戳、双语对照、分P合并的字幕稿。
- 用户需要一份字幕质量报告，判断是否值得人工校对。

不适用：

- 需要“翻译”字幕：本 skill 只做双语对齐，不做机器翻译。
- 需要精确的说话人分离：自动 diarization 尚未启用；只保留字幕里已有的 `[说话人]` 标记。
- 需要绕过 B 站登录/付费/地区限制：请用户提供其有权使用的 Cookie，或改用其本地文件。

## 安装与调用

把整个目录复制到 DSH 的 skills 目录（或运行 `install.ps1`），然后在目录内执行：

```bash
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx
```

如果只是临时使用，也可以不安装，直接在 skill 目录运行 `main.py`。

## 一条命令

```bash
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx
```

输出在 `output/`：

- `标题_BV号.md`
- `标题_BV号.docx`
- `标题_BV号.quality.json`（质量报告）
- `标题_BV号.segments.json`（清洗后的结构化字幕）
- `_manifest.json`（本次运行的汇总清单）

## 输入 / 输出契约

### 输入

| 类型 | 示例 |
| --- | --- |
| Bilibili 视频 | `https://www.bilibili.com/video/BV1xx411c7mD?p=2` |
| BV / av 号 | `BV1xx411c7mD`、`av80433022` |
| 番剧 | `https://www.bilibili.com/bangumi/play/ep123456`、`.../ss28747` |
| 短链 | `https://b23.tv/xxxxxx` |
| 本地视频 | `input.mp4`、`input.mkv` |
| 外挂字幕 | `--subtitle input.srt`（也支持 `.ass/.vtt/.json/.txt`） |
| 目录/批量 | `python main.py ./videos --format md,docx` |

### 输出

- 文档文件路径（Markdown/Word/PDF/TXT/SRT）。
- 结构化字幕：`[{start, end, text, speaker?, lang?, confidence?, translation?}]`。
- 质量报告：字幕来源、语言、覆盖率、低置信度片段、警告、前/中/尾抽样。
- 处理尝试记录：每个 provider 的成功/失败/跳过及原因。

## 字幕来源优先级

按以下顺序尝试，失败会自动降级，除非显式禁用：

1. **用户外挂字幕**（`--subtitle`）：质量最高，完全可控。
2. **Bilibili 平台字幕 / AI 字幕**：通过 `x/player/v2` 读取，需要 `SESSDATA`。
3. **本地视频内嵌字幕**：`ffprobe` 检测 + `ffmpeg` 提取为 SRT。
4. **硬字幕 OCR**：仅本地视频，`--ocr` 开启；实验性。
5. **Whisper 语音转写**：`--asr` 开启或自动兜底；首次会下载模型。

> 没有登录时，B 站通常不返回字幕列表。此时会给出 `LOGIN_REQUIRED`，并提示提供 Cookie 或启用 ASR。这是平台限制，不是链接错误。

## Bilibili 登录（平台字幕必需）

平台字幕接口只对登录会话返回 `subtitle_url`。推荐用环境变量，避免出现在命令历史里：

```powershell
$env:BILIBILI_SESSDATA = "你的 SESSDATA"
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx
```

获取方式：浏览器登录 bilibili.com → 开发者工具 → Application/应用 → Cookies → `bilibili.com` → 复制 `SESSDATA` 的值。

也支持：

```bash
python main.py URL --sessdata "SESSDATA的值"
python main.py URL --cookie "SESSDATA=...; bili_jct=..."
python main.py URL --cookies cookies.txt
```

- Cookie 等同账号凭证，**不要**写入仓库、文档或发到公开频道。
- 本 skill 只在内存中使用 Cookie，日志和报告中会脱敏。
- Cookie 过期后重新复制即可。

## 常用参数

| 参数 | 作用 |
| --- | --- |
| `--format md,docx,pdf,txt,srt,json` | 输出格式，逗号分隔；默认 `md` |
| `-o, --output PATH` | 单输入 + 单格式时指定输出文件 |
| `--out-dir DIR` | 输出目录，默认 `output` |
| `--title TEXT` | 覆盖文档标题（默认用视频标题/文件名） |
| `--subtitle PATH` | 外挂字幕文件或目录（最高优先级） |
| `--language zh` | 首选字幕/转写语言；平台字幕按语言匹配 |
| `--bilingual` | 双语对照；有两条字幕轨时按时间对齐，单轨时尝试按行拆分 |
| `--timestamps` / `--no-timestamps` | 正文是否显示 `[00:12]`，默认显示 |
| `--merge-sentences` / `--no-merge-sentences` | 是否合并被硬切开的短句，默认合并 |
| `--no-auto-punctuation` | 关闭 ASR/OCR 的自动补标点（默认开启） |
| `--pages auto/all/1,3-5` | 分P选择；默认只处理链接指定的 P，未指定则 P1 |
| `--template default/minimal/文件.md` | Markdown 模板 |
| `--quality-report PATH` | 质量报告 JSON 路径 |
| `--no-quality` | 不生成质量报告，也不在文档中附加处理信息 |
| `--glossary terms.json` | 术语替换，如 `{"DeepSeek":"深度求索"}` |
| `--json-summary` | stdout 输出机器可读摘要（便于 agent 读取） |
| `--asr` / `--no-asr` | 允许/禁止 Whisper 兜底；默认自动（已安装才尝试） |
| `--asr-model small` | `tiny/base/small/medium`；默认 `small` |
| `--model-dir DIR` | Whisper 模型缓存目录（默认 `./.vsub-models-cache`） |
| `--ocr` | 对本地视频硬字幕做 OCR（实验性） |
| `--ffmpeg PATH` | 指定 ffmpeg/ffprobe 路径 |
| `--strict` | 任一输入失败或质量 `fail` 时返回非零 |

完整参数：`python main.py --help`。

## 推荐工作流（agent）

1. 判断输入：
   - Bilibili 链接/BV/av → 直接跑。
   - 本地视频 → 检查同名 `.srt/.vtt/.ass`，有就优先 `--subtitle`；没有则尝试内嵌字幕。
   - 只有字幕文件 → 也可直接作为输入。
2. 先跑默认输出，不要在没看质量报告前就开 ASR：

   ```bash
   python main.py "<链接>" --format md,docx --out-dir output
   ```

3. 如果报 `LOGIN_REQUIRED`：
   - 告诉用户平台字幕需要 `SESSDATA`，并给出设置方法；不要反复重试。
   - 用户没有 Cookie 时，再建议 `--asr`（说明首次下载模型、耗时、可能产生识别错误）。
4. 检查 `<stem>.quality.json`：
   - `status=ok`：直接交付。
   - `status=warn`：看 `warnings`，尤其是覆盖率、重叠、低置信度；在交付说明中提醒。
   - `status=fail`：不要假装成功；报告失败原因，建议外挂字幕/ASR/OCR。
5. 用 `present` 把 `.md` / `.docx` 作为最终文件交付；质量报告只在用户需要时附上。

执行环境：

- 优先使用 `load_workspace_dependencies` 返回的 Python（自带 `python-docx`）。
- Windows PowerShell 调用示例：

  ```powershell
  & "C:\...\python.exe" main.py "<链接>" --format md,docx --out-dir output
  ```

- 所有输出、临时文件必须放在会话工作区内；不要用系统临时目录（可能被沙箱拒绝）。

## 质量报告字段

```json
{
  "status": "ok | warn | fail",
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
  "duplicate_segments": 1,
  "gaps_over_10s": 2,
  "warnings": ["..."],
  "samples": {"head": [], "middle": [], "tail": []}
}
```

- `duration_covered`：相对完整视频时长；片头/片尾广告被清理后会偏低。
- `coverage_span`：相对首尾字幕之间的内容区间；更能反映“说话部分是否覆盖”。
- `samples`：前/中/尾各最多 5 段，便于人工抽查。
- `status=fail` 的常见原因：没有片段、覆盖率低于 30%、所有分P失败。

## 失败与降级

| 情况 | 行为 |
| --- | --- |
| 外挂字幕解析失败 | 记录失败，继续尝试平台/内嵌字幕 |
| 平台字幕 `LOGIN_REQUIRED` | 提示设置 `SESSDATA`；若已安装 faster-whisper 且允许 ASR，则自动转写 |
| 平台无字幕轨 | 提示 `NO_SUBTITLE`；可 `--asr` 或 `--subtitle` |
| 内嵌字幕是 PGS/VobSub 位图 | 无法直接转 SRT；提示改用 OCR/外挂 |
| ASR 未安装 | 跳过并给出 `pip install faster-whisper`；不会静默失败 |
| 某个输出格式失败 | 其他格式继续生成；`quality.warnings` 记录；只有全部失败才报 `RENDER_FAILED` |
| 批量中部分失败 | 成功的继续输出；`_manifest.json` 与 `*.error.json` 记录失败 |

退出码：

- `0` 成功（批量时表示至少有一个成功）
- `2` 输入/链接/API/解析错误
- `3` 没有字幕、需要登录、质量失败
- `4` 缺少依赖（ffmpeg/Whisper/docx 等）
- `5` 文档渲染失败
- `1` 未预期错误

## 示例

```bash
# 基础：平台字幕 → Markdown + Word
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --format md,docx

# 只要 Word，指定文件名
python main.py "BV1xx411c7mD" --format docx -o "论文笔记.docx"

# 多分P + 时间戳 + 质量报告
python main.py "https://www.bilibili.com/video/BV1xx411c7mD?p=1" --pages all --format md

# 外挂字幕优先
python main.py "input.mp4" --subtitle "input.srt" --format md,docx

# 双语（平台有两条轨时自动对齐）
python main.py "BV1xx411c7mD" --bilingual --language zh --format md,docx

# 无登录、用 ASR 兜底（首次下载模型）
python main.py "BV1xx411c7mD" --asr --asr-model small --format md,docx

# 批量目录
python main.py "./videos" --format md,docx --out-dir output/batch

# 本地硬字幕 OCR（实验性）
python main.py "input.mp4" --ocr --ocr-fps 2 --format md
```

## 局限

- 平台字幕是否可用取决于视频、账号、地区和 UP 主设置；本 skill 无法绕过权限。
- AI 字幕本身可能错字、漏句、时间轴漂移；质量报告只能提示，不能替代人工校对。
- 双语是“时间对齐”，不是翻译；两条轨语言不同才会对照。
- 自动说话人分离未实现；只解析字幕中的 `[张三]`、`【张三】`、`张三：` 等标记。
- OCR 仅本地视频，默认底部 30% 区域；动画/竖屏/字幕位置漂移时需要调 `--ocr-crop` 或 `--ocr-full-frame`。
- PDF 需要 LibreOffice 或 `reportlab`；否则会明确报错，不影响 md/docx。
- 长视频 ASR 可能很慢；`small` 模型首次下载约 460MB。

## 版权与隐私

- 仅处理用户有权使用的视频/字幕；不要用本 skill 批量抓取受版权保护的内容。
- 字幕文档中会保留原视频标题、UP 主、链接，便于溯源。
- Cookie、签名 CDN URL 不会写入日志/质量报告；仍建议用户不要在公开场合粘贴 Cookie。
- 临时音频/抽帧文件默认在输出目录的 `.vsub-tmp` 下，运行结束自动清理；`--keep-temp` 可保留用于排查。

## 文件说明

```text
dsh-bilibili-subtitles/
├── SKILL.md
├── README.md
├── main.py                  # CLI 入口
├── vsub/
│   ├── bilibili.py          # URL/API/字幕/音频
│   ├── input_adapter.py     # 输入适配
│   ├── pipeline.py          # 五层流水线编排
│   ├── providers/           # external/bilibili/embedded/ocr/asr
│   ├── parsers/             # srt/vtt/ass/bilibili-json/plain
│   ├── cleaners/            # 清洗、合并、双语、术语
│   ├── renderers/           # md/docx/pdf/txt/srt/json
│   └── quality.py           # 质量校验
├── templates/
├── tests/
└── requirements.txt
```
