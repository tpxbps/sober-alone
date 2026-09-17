import { useId, useLayoutEffect, useRef, useState } from 'react';
import { CircleHelp, Maximize2 } from 'lucide-react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Markdown } from '@/components/ui/Markdown';

export function WorkshopField({ label, value, onChange, help, audience, compact = false, target }: {
  label: string; value?: string; onChange: (value: string) => void; help?: string; audience?: string; compact?: boolean; target?: string;
}) {
  const id = useId();
  const [preview, setPreview] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.max(compact ? 44 : 140, input.current.scrollHeight)}px`; }
  }, [value, preview, compact]);
  return <section data-field-target={target} className="scroll-mt-6 rounded-xl border border-border/50 bg-card/40 p-4 transition-shadow focus-within:border-primary/50">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2"><label htmlFor={id} className="text-sm font-medium">{label}</label>
        {help && <Tooltip.Root><Tooltip.Trigger asChild><button type="button" aria-label={`${label}说明`} className="text-muted-foreground"><CircleHelp className="size-3.5" /></button></Tooltip.Trigger>
          <Tooltip.Portal><Tooltip.Content side="top" className="z-[70] max-w-64 rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-xl">{help}</Tooltip.Content></Tooltip.Portal></Tooltip.Root>}
        {audience && <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">{audience}</span>}
      </div>
      {!compact && <div className="flex gap-3 text-xs text-muted-foreground">
        <button type="button" onClick={() => setPreview(!preview)} className="hover:text-primary">{preview ? '编辑' : '预览'}</button>
        <button type="button" aria-label={`放大编辑${label}`} onClick={() => setExpanded(true)} className="hover:text-primary"><Maximize2 className="size-3.5" /></button>
      </div>}
    </div>
    {preview ? <Markdown className="min-h-24 text-sm leading-7">{value || '暂无内容'}</Markdown> :
      <textarea ref={input} id={id} aria-label={label} value={value || ''} onChange={e => onChange(e.target.value)} rows={compact ? 1 : 5}
        className="block w-full resize-y overflow-hidden bg-transparent text-sm leading-7 outline-none placeholder:text-muted-foreground" />}
    {help && <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{help}</p>}
    <Dialog open={expanded} onOpenChange={setExpanded}><DialogContent className="sm:max-w-4xl">
      <DialogTitle>{label}</DialogTitle><DialogDescription>{audience || '作者编辑区'} · 修改同步保留在当前草稿</DialogDescription>
      <textarea aria-label={`放大编辑：${label}`} value={value || ''} onChange={e => onChange(e.target.value)}
        className="h-[60dvh] w-full resize-none rounded-lg border border-border bg-background p-4 text-sm leading-7 focus:outline-primary" />
    </DialogContent></Dialog>
  </section>;
}
