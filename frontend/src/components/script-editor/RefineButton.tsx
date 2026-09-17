import { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { RotateCcw, X } from 'lucide-react';
import { useEditorStore } from '@/stores/editorStore';
import type { GameDataSections } from '@/types/editor';

export function RefineButton({ step, content, gameData, humanReview, prompt, getPrompt, disabled = false }: {
  step: string; content?: string; gameData?: GameDataSections; humanReview?: string; prompt?: string; disabled?: boolean;
  getPrompt?: () => string | undefined;
}) {
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const loading = useEditorStore(s => s.isLoading);
  const count = useEditorStore(s => s.workflowState?.refinement_counts?.[step] || 0);
  const resume = useEditorStore(s => s.resumeWorkflow);
  const desktop = typeof window !== 'undefined' && window.matchMedia('(min-width: 768px)').matches;
  const changeOpen = (value: boolean) => {
    if (value && trigger.current) {
      const rect = trigger.current.getBoundingClientRect();
      setPosition({ left: Math.max(16, Math.min(rect.left, window.innerWidth - 400)), top: Math.max(16, rect.top - 300) });
    }
    setOpen(value);
  };
  return <Dialog.Root open={open} onOpenChange={changeOpen} modal={!desktop}>
    <Dialog.Trigger ref={trigger} disabled={disabled || loading} className="inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2.5 text-sm hover:bg-secondary disabled:opacity-40">
      <RotateCcw className="size-3.5" />输入改进方向 · 重新生成
    </Dialog.Trigger>
    <Dialog.Portal>
      {!desktop && <Dialog.Overlay className="fixed inset-0 z-50 bg-background/70" />}
      <Dialog.Content style={desktop ? position : undefined}
        className={`fixed z-50 w-[calc(100%-2rem)] max-w-96 rounded-xl border border-border bg-popover p-5 shadow-2xl outline-none ${desktop ? '' : 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2'}`}>
        <Dialog.Title className="pr-5 font-semibold">{count >= 3 ? '试试直接修改' : '这一次，希望怎样改进？'}</Dialog.Title>
        <Dialog.Description className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {count >= 3 ? '多次生成可能难以继续改善。建议直接编辑当前内容，或先进入下一阶段。' : '以当前编辑稿为基础，保留未要求修改的内容。'}
        </Dialog.Description>
        {count < 3 && <form onSubmit={event => {
          event.preventDefault();
          if (!feedback.trim()) return;
          setOpen(false);
          void resume('regenerate', content, getPrompt?.() || prompt, gameData, humanReview, undefined, undefined, feedback.trim());
        }}>
          <textarea aria-label="改进方向" value={feedback} required maxLength={8000} onChange={e => setFeedback(e.target.value)}
            placeholder="例如：保留人物关系，让案发前的冲突更克制，并补清关键行动的时间。"
            className="mt-4 min-h-28 w-full resize-y rounded-lg border border-border bg-background p-3 text-sm focus:outline-primary" />
          <button disabled={!feedback.trim()} className="mt-3 w-full rounded-lg bg-primary px-4 py-2.5 text-sm text-primary-foreground disabled:opacity-40">按此方向改写</button>
        </form>}
        <Dialog.Close aria-label="关闭改进方向" className="absolute right-4 top-4"><X className="size-4" /></Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
