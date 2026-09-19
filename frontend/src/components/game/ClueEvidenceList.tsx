import type { PublicClue } from '@/types/game';
import { Markdown } from '@/components/ui/Markdown';
import { ClueImage } from './ClueImage';

export function ClueEvidenceList({ clues }: { clues: PublicClue[] }) {
  return <div className="cinema-evidence-list">{clues.map(clue => <details key={clue.id}>
    <summary><ClueImage media={clue.media} thumbnail className="cinema-evidence-thumb" /><span>{clue.summary}</span><span className="cinema-expand">＋</span></summary>
    <div className="cinema-evidence-body"><ClueImage media={clue.media} className="cinema-evidence-image" /><Markdown>{clue.content}</Markdown></div>
  </details>)}</div>;
}
