import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Search } from 'lucide-react';
import * as HoverCard from '@radix-ui/react-hover-card';
import type { PublicClue } from '@/types/game';
import { Markdown } from '@/components/ui/Markdown';
import { ClueImage } from './ClueImage';

export function ClueDetails({ clues }: { clues: PublicClue[] }) {
  return <div className="max-h-[65dvh] overflow-y-auto overscroll-contain scrollbar-thin divide-y divide-amber-200/15">
    {clues.map((clue, index) => <section key={clue.id} className="py-4 first:pt-0 last:pb-0">
      <header className="mb-3">
        {clue.media?.status === 'ready' && <ClueImage media={clue.media}
          className="clue-detail-image mb-3 h-[164px] w-full rounded-lg border border-white/10 object-cover" />}
        <div className="min-w-0">
          <p className="mb-1.5 text-[10px] tracking-wider text-amber-200/50">第 {clue.stage} 轮公开{clues.length > 1 && ` · 证据 ${String(index + 1).padStart(2, '0')}`}</p>
          <h3 className="text-sm font-semibold leading-relaxed text-amber-100">{clue.summary}</h3>
        </div>
      </header>
      <Markdown className="text-[13px] leading-[1.85] text-foreground/85">{clue.content}</Markdown>
    </section>)}
  </div>;
}

export function ClueCitationHover({ clue, clues: group, children }: {
  clue?: PublicClue; clues?: PublicClue[]; children?: ReactNode;
}) {
  const clues = group ?? (clue ? [clue] : []);
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const cancelClose = () => clearTimeout(closeTimer.current);
  // Always close after leaving the trigger/panel, including after selecting detail text.
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), 180);
  };
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  if (!clues.length) return <>{children}</>;
  const label = children ? `查看 ${clues.length} 条引用线索` : `查看线索 ${clues[0].summary}`;
  const trigger = <span tabIndex={0} aria-label={label} data-clue-citation=""
    onFocus={event => { if (!event.currentTarget.matches(':focus-visible')) event.preventDefault(); }}
    onPointerEnter={cancelClose} onPointerLeave={scheduleClose}
    className={children
      ? 'inline cursor-text text-left leading-[inherit] text-inherit focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/60 rounded-sm'
      : 'inline-flex cursor-default min-h-6 max-w-60 items-center gap-1 rounded-full border border-amber-400/35 bg-amber-400/10 px-1.5 py-0.5 align-middle text-[11px] font-medium text-amber-200 hover:bg-amber-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/60'}>
    {children ? <><span className="underline decoration-amber-300/70 decoration-dashed decoration-2 underline-offset-4">{children}</span>{'\u2060'}<sup className="ml-0.5 inline rounded-[3px] border border-amber-300/50 bg-amber-400/10 px-0.5 text-[9px] leading-none text-amber-200">{clues.length}</sup></>
      : <><ClueImage media={clues[0].media} thumbnail className="h-5 w-6 shrink-0 rounded-sm object-cover" fallback={<Search className="h-3 w-3 shrink-0" />} /><span className="truncate">{clues[0].summary}</span></>}
  </span>;
  return <HoverCard.Root open={open} openDelay={150} closeDelay={180} onOpenChange={setOpen}>
    <HoverCard.Trigger asChild>{trigger}</HoverCard.Trigger><HoverCard.Portal>
    <HoverCard.Content role="tooltip" side="top" collisionPadding={12} onPointerEnter={cancelClose} onPointerLeave={scheduleClose}
      className="z-[90] w-[min(28rem,calc(100vw-2rem))] select-text rounded-xl border border-amber-300/20 bg-popover p-4 text-popover-foreground shadow-2xl">
      <ClueDetails clues={clues} /><HoverCard.Arrow className="fill-popover" />
    </HoverCard.Content></HoverCard.Portal></HoverCard.Root>;
}
