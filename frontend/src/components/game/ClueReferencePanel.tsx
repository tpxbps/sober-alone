import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Search, X } from 'lucide-react';
import * as HoverCard from '@radix-ui/react-hover-card';
import * as Dialog from '@radix-ui/react-dialog';
import type { PublicClue } from '@/types/game';
import { Markdown } from '@/components/ui/Markdown';
import { ClueImage } from './ClueImage';

export function ClueDetails({ clues }: { clues: PublicClue[] }) {
  return <div className="max-h-[65dvh] overflow-y-auto overscroll-contain scrollbar-thin divide-y divide-amber-200/15">
    {clues.map((clue, index) => <section key={clue.id} className="py-4 first:pt-0 last:pb-0">
      <header className="mb-3 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-1.5 text-[10px] tracking-wider text-amber-200/50">第 {clue.stage} 轮公开{clues.length > 1 && ` · 证据 ${String(index + 1).padStart(2, '0')}`}</p>
          <h3 className="text-sm font-semibold leading-relaxed text-amber-100">{clue.summary}</h3>
        </div>
        {clue.media?.status === 'ready' && <figure className="clue-detail-figure w-24 shrink-0">
          <ClueImage media={clue.media} thumbnail className="h-16 w-24 rounded-md border border-white/10 object-cover" />
          <figcaption className="mt-1 text-right text-[9px] text-muted-foreground">场景示意</figcaption>
        </figure>}
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
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches);
  const pinned = useRef(false);
  const suppress = useRef(false);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 640px)');
    const change = () => setMobile(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  const close = () => { pinned.current = false; suppress.current = true; setOpen(false); };
  const toggle = () => {
    if (pinned.current) close();
    else { suppress.current = false; pinned.current = true; setOpen(true); }
  };
  if (!clues.length) return <>{children}</>;
  const label = children ? `查看 ${clues.length} 条引用线索` : `查看线索 ${clues[0].summary}`;
  const trigger = <button type="button" aria-label={label} aria-expanded={open}
    onPointerLeave={() => { suppress.current = false; }} onClick={toggle}
    className={children
      ? 'inline text-left leading-[inherit] text-inherit focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/60 rounded-sm'
      : 'inline-flex min-h-6 max-w-60 items-center gap-1 rounded-full border border-amber-400/35 bg-amber-400/10 px-1.5 py-0.5 align-middle text-[11px] font-medium text-amber-200 hover:bg-amber-400/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/60'}>
    {children ? <><span className="underline decoration-amber-300/70 decoration-dashed decoration-2 underline-offset-4">{children}</span><sup className="ml-0.5 inline-flex h-3.5 min-w-3.5 items-center justify-center rounded-[3px] border border-amber-300/50 bg-amber-400/10 px-0.5 text-[9px] leading-none text-amber-200">{clues.length}</sup></>
      : <><ClueImage media={clues[0].media} thumbnail className="h-5 w-6 shrink-0 rounded-sm object-cover" fallback={<Search className="h-3 w-3 shrink-0" />} /><span className="truncate">{clues[0].summary}</span></>}
  </button>;
  if (mobile) return <Dialog.Root open={open} onOpenChange={value => { if (!value) close(); }}>
    <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-[100] bg-black/65" />
      <Dialog.Content className="fixed inset-x-0 bottom-0 z-[101] max-h-[85dvh] rounded-t-2xl border border-amber-200/20 bg-popover p-5 pb-8 shadow-2xl">
        <div className="mb-4 flex items-center justify-between"><Dialog.Title className="text-base font-semibold">引用线索 · {clues.length}</Dialog.Title><Dialog.Close aria-label="关闭线索详情" className="p-2"><X className="h-5 w-5" /></Dialog.Close></div>
        <Dialog.Description className="sr-only">已公开的证据图片与完整文字</Dialog.Description><ClueDetails clues={clues} />
      </Dialog.Content></Dialog.Portal>
  </Dialog.Root>;
  return <HoverCard.Root open={open} openDelay={150} closeDelay={180} onOpenChange={value => {
    if ((value && suppress.current) || (!value && pinned.current)) return;
    setOpen(value);
  }}><HoverCard.Trigger asChild>{trigger}</HoverCard.Trigger><HoverCard.Portal>
    <HoverCard.Content role="tooltip" side="top" collisionPadding={12} onEscapeKeyDown={close}
      className="z-[90] w-[min(26rem,calc(100vw-2rem))] select-text rounded-xl border border-amber-300/20 bg-popover p-4 text-popover-foreground shadow-2xl">
      <ClueDetails clues={clues} /><HoverCard.Arrow className="fill-popover" />
    </HoverCard.Content></HoverCard.Portal></HoverCard.Root>;
}
