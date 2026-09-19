import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Fingerprint, X, ArrowLeft } from 'lucide-react';
import type { PublicClue } from '@/types/game';
import { ClueEvidenceList } from './ClueEvidenceList';
import './cluePresentation.css';

/** Read-only access to disclosed evidence; never acknowledges or advances a game. */
export function ClueArchive({ clues }: { clues: PublicClue[] }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const rounds = [...new Set(clues.map(clue => clue.stage ?? 1))].sort((a, b) => a - b);
  const round = selected != null && rounds.includes(selected) ? selected : rounds.at(-1);
  const current = clues.filter(clue => (clue.stage ?? 1) === round);
  if (!clues.length) return null;
  return <Dialog.Root open={open} onOpenChange={value => { setOpen(value); if (value) setSelected(null); }}>
    <Dialog.Trigger asChild><button type="button" className="clue-archive-trigger" aria-label={`查看已公开线索（${clues.length}条）`}>
      <Fingerprint aria-hidden="true" /><span>线索</span><sup>{clues.length}</sup>
    </button></Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-[110] bg-black/80" />
      <Dialog.Content className="clue-cinema clue-archive">
        <header className="cinema-header"><div><p className="cinema-eyebrow">已公开的材料 · 随时回看</p><Dialog.Title>线索档案</Dialog.Title></div>
          <Dialog.Close className="clue-archive-close" aria-label="关闭线索档案"><X /></Dialog.Close></header>
        <main className="cinema-end">
          <Dialog.Description className="cinema-end-intro">重看细节，寻找此前忽略的联系。</Dialog.Description>
          <nav className="clue-archive-rounds" aria-label="已公开线索轮次">{rounds.map(value => <button type="button" key={value}
            aria-pressed={round === value} onClick={() => setSelected(value)}>第 {value} 轮<span>{clues.filter(clue => (clue.stage ?? 1) === value).length}</span></button>)}</nav>
          <ClueEvidenceList key={round} clues={current} />
          <div className="cinema-end-actions"><Dialog.Close className="cinema-continue"><ArrowLeft />返回讨论</Dialog.Close></div>
        </main>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
