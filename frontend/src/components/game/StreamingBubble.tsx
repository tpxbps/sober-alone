import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { useGameStore } from "@/stores/gameStore";
import { DynamicDot } from "@/components/ui/DynamicDot";
import { GameMessageMarkdown } from "@/components/ui/GameMessageMarkdown";
import type { GameRecord } from "@/types/game";

/** The same body is mounted for optimistic, streaming and committed messages. */
export function StreamingBubble({ record, isHuman }: { record: GameRecord; isHuman: boolean }) {
  const turn = useGameStore(s => s.activeTurn?.turn_id === record.turn_id ? s.activeTurn : null);
  const characters = useGameStore(s => s.characters);
  const publicClues = useGameStore(s => s.publicClues);
  const retry = useGameStore(s => s.retryActiveTurn);
  const reconnecting = useGameStore(s => s.isReconnecting);
  const content = turn?.content ?? record.content;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!turn) return;
    const frame = requestAnimationFrame(() => {
      const parent = ref.current?.closest<HTMLElement>('[data-chat-scroll]');
      if (parent && parent.dataset.followTail !== 'false') parent.scrollTop = parent.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [content, turn]);
  const failed = turn && ['failed', 'blocked'].includes(turn.status);
  const thinking = turn && !content.trim() && ['queued', 'speaking'].includes(turn.status);
  return <div ref={ref} data-speech-body>
    {thinking && <div className="text-xs text-muted-foreground flex items-center gap-1.5" data-thinking>
      <Loader2 className="w-3 h-3 animate-spin" /><span>思考中</span><DynamicDot />
    </div>}
    <GameMessageMarkdown className="text-sm" characters={characters} publicClues={publicClues}
      allowedCitationIds={record.stage === 'intro' ? [] : (turn?.clue_refs ?? record.clue_refs ?? [])}
      preserveWhitespace={isHuman}>{content}</GameMessageMarkdown>
    {record.pending && !turn && <p className="mt-1 text-xs text-muted-foreground">将在当前回应结束后发送</p>}
    {failed && <div className="mt-2 flex flex-wrap items-start gap-2 text-xs text-muted-foreground" role="status">
      <span className="min-w-0 break-words">{turn.error_message}</span>
      <button type="button" className="shrink-0 text-primary underline disabled:opacity-50" disabled={reconnecting}
        onClick={() => void retry()}>重试本轮</button>
    </div>}
  </div>;
}
