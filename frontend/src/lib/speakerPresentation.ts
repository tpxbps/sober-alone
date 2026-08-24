import type { GameStage } from "@/types/game";

export function resolveDisplayedSpeakerId({
  stage,
  isAutoSpeakPaused,
  isStreaming,
  streamingSpeakerId,
  currentSpeakerId,
}: {
  stage: GameStage;
  isAutoSpeakPaused: boolean;
  isStreaming: boolean;
  streamingSpeakerId: string | null;
  currentSpeakerId: string | null;
}): string | null {
  if (isStreaming) return streamingSpeakerId || currentSpeakerId;
  if (stage === "free_discussion" && isAutoSpeakPaused) return null;
  return currentSpeakerId;
}
