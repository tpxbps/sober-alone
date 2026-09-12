import type { Script } from "@/types/game";

const WORKSHOP_TAG_ALIASES = new Set([
  "AI生成",
  "AI 生成",
  "AI创作",
  "AI辅助",
  "用户创作",
  "创作工坊",
]);

export function getScriptDisplayTags(script: Script): string[] {
  const sourceTags = (script.tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  const fromWorkshop = script.is_ai_generated || sourceTags.some((tag) => WORKSHOP_TAG_ALIASES.has(tag));
  const normalized = sourceTags.filter((tag) => !WORKSHOP_TAG_ALIASES.has(tag));
  return [...new Set([...(fromWorkshop ? ["创作工坊"] : []), ...normalized])];
}
