import type { EditorInterruptInfo, GameDataSections } from "@/types/editor";

export function cloneGameDataSections(
  source: GameDataSections | null | undefined
): GameDataSections | null {
  if (!source) return null;
  return structuredClone(source);
}

export function workflowDraftKey(
  currentStep: string,
  interruptInfo: EditorInterruptInfo | null,
  checkpointId?: string | null
): string {
  if (checkpointId) return `checkpoint:${checkpointId}`;
  return [
    currentStep || "idea",
    interruptInfo?.step || "no-interrupt",
    interruptInfo?.generated_content || "",
    interruptInfo?.quality_report?.report_id || "",
    interruptInfo?.game_data_sections ? JSON.stringify(interruptInfo.game_data_sections) : "",
  ].join(":");
}

