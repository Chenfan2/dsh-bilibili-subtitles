/**
 * dsh-bilibili-subtitles —— DSH plugin entry.
 *
 * Registers the skill `dsh-bilibili-subtitles` and exposes the skill package
 * directory as its resource base, so the agent can run:
 *
 *   python main.py "<bilibili-url>" --format md,docx
 *
 * The Python implementation lives next to SKILL.md; no network is used at
 * plugin load time.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const name = "dsh-bilibili-subtitles";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const SKILL_NAME = "dsh-bilibili-subtitles";
const DESCRIPTION =
	"当用户需要从 Bilibili 视频链接（BV/av/ep/ss、b23.tv 短链）或本地视频中提取字幕，" +
	"并整理成 Markdown/Word/PDF/TXT/SRT 文档时使用；优先使用平台/外挂字幕，ASR/OCR 仅作兜底。";

function readSkillBody() {
	const raw = readFileSync(path.join(ROOT, "SKILL.md"), "utf8");
	// The registry adds its own metadata; feed it the markdown body only.
	return raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "").trimStart();
}

export function apply(ctx) {
	ctx.skills.register({
		name: SKILL_NAME,
		description: DESCRIPTION,
		content: readSkillBody(),
		resourceBase: { kind: "directory", path: ROOT },
	});
}
