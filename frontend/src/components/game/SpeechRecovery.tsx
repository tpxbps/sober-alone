import { useState } from "react";
import { useGameStore } from "@/stores/gameStore";
import { GameMessageMarkdown } from "@/components/ui/GameMessageMarkdown";

export function SpeechRecovery() {
  const generation = useGameStore(state => state.speechGeneration);
  const connectionError = useGameStore(state => state.speechConnectionError);
  const characters = useGameStore(state => state.characters);
  const clues = useGameStore(state => state.publicClues);
  const retry = useGameStore(state => state.retryAISpeech);
  const skip = useGameStore(state => state.skipAISpeech);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (generation?.status !== 'failed' && !connectionError) return null;
  const name = characters.find(character => character.character_id === generation?.character_id)?.name || 'AI 角色';
  const act = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch { setError("操作未完成，请重试。"); } finally { setBusy(false); }
  };
  return <section aria-label="发言恢复" className="mx-4 my-3 rounded-xl border border-border bg-card p-4 space-y-3">
    <p role="alert" className="text-sm">{connectionError || `${name}的发言未完成，请重试或跳过本次发言。`}</p>
    {generation?.partial_content && <div className="max-h-40 overflow-auto text-sm text-muted-foreground">
      <p className="mb-2 text-xs">未完成的发言</p>
      <GameMessageMarkdown characters={characters} publicClues={clues} allowedCitationIds={clues.map(clue => clue.id)}>{generation.partial_content}</GameMessageMarkdown>
    </div>}
    <div className="flex gap-3">
      <button disabled={busy} onClick={() => void act(retry)} className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">{busy ? '处理中…' : '重试'}</button>
      <button disabled={busy || generation?.status !== 'failed'} onClick={() => void act(skip)} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">跳过本次发言</button>
    </div>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
  </section>;
}
