# Changelog

## 0.2.0

- Renamed the skill to `dsh-bilibili-subtitles`.
- Added a DSH plugin bundle entry (`dsh.bundle` + `cordis.patch.yml`) so the
  skill can be installed from a plugin market.
- Documented the SESSDATA requirement and the `.secrets/bili_sessdata.txt`
  workflow (the CLI still requires `--sessdata` / env; it does not auto-read
  secrets).
- Kept the Python CLI, tests, templates and optional ASR/OCR/PDF providers.

## 0.1.0

- Initial release: Bilibili URL resolution, platform/AI subtitles, external /
  embedded / OCR / ASR fallback, cleaning, bilingual alignment, Markdown /
  DOCX / PDF / TXT / SRT / JSON output, quality report.
