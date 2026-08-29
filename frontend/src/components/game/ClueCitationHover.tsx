import { useRef, useState } from "react";
import { Search } from "lucide-react";
import * as HoverCard from "@radix-ui/react-hover-card";

import type { PublicClue } from "@/types/game";

export function ClueCitationHover({ clue }: { clue: PublicClue }) {
  const [open, setOpen] = useState(false);
  const pinnedRef = useRef(false);
  const suppressHoverOpenRef = useRef(false);

  const closePinnedCard = (suppressHover = false) => {
    suppressHoverOpenRef.current = suppressHover;
    pinnedRef.current = false;
    setOpen(false);
  };

  const togglePinnedCard = () => {
    if (pinnedRef.current) {
      closePinnedCard(true);
      return;
    }
    suppressHoverOpenRef.current = false;
    pinnedRef.current = true;
    setOpen(true);
  };

  return (
    <HoverCard.Root
      open={open}
      openDelay={150}
      closeDelay={180}
      onOpenChange={(nextOpen) => {
        if (nextOpen && suppressHoverOpenRef.current) return;
        if (!nextOpen && pinnedRef.current) return;
        setOpen(nextOpen);
      }}
    >
        <HoverCard.Trigger asChild>
          <button
            type="button"
            aria-label={`查看线索 ${clue.summary}`}
            aria-expanded={open}
            onPointerLeave={() => {
              suppressHoverOpenRef.current = false;
            }}
            onClick={togglePinnedCard}
            className="inline-flex h-6 max-w-44 items-center gap-1 rounded-full border border-amber-400/35 bg-amber-400/10 px-2 text-[10px] font-medium text-amber-200 shadow-sm transition-colors hover:bg-amber-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/60"
          >
            <Search className="h-3 w-3 shrink-0" />
            <span className="truncate">{clue.summary}</span>
          </button>
        </HoverCard.Trigger>
        <HoverCard.Portal>
          <HoverCard.Content
            role="tooltip"
            side="top"
            collisionPadding={12}
            onEscapeKeyDown={() => closePinnedCard(true)}
            className="z-[90] w-[min(24rem,calc(100vw-2rem))] select-text rounded-xl border border-amber-300/20 bg-popover p-3 text-popover-foreground shadow-2xl"
          >
            <div className="mb-1 flex items-center gap-3">
              <span className="text-xs font-semibold text-amber-200">{clue.summary}</span>
            </div>
            <p className="mb-2 text-[10px] text-muted-foreground">第 {clue.stage} 轮公开线索</p>
            <p className="whitespace-pre-wrap text-xs leading-relaxed">{clue.content}</p>
            <HoverCard.Arrow className="fill-popover" />
          </HoverCard.Content>
        </HoverCard.Portal>
    </HoverCard.Root>
  );
}
