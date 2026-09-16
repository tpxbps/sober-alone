import type { PublicClue } from '@/types/game';

export function speechClues(stage: string, clues: PublicClue[]): PublicClue[] {
  return ['clue_analysis', 'free_discussion', 'summary', 'vote', 'review', 'completed'].includes(stage)
    ? clues.map(clue => ({ ...clue })) : [];
}

export function citedIds(content: string, clues: PublicClue[]): string[] {
  const allowed = new Set(clues.map(clue => clue.id.toLowerCase()));
  return [...new Set(Array.from(content.matchAll(/\[((?:c[0-9]{2,4})|(?:clue-[a-z0-9]{12}))\]/gi), match => match[1].toLowerCase()))]
    .filter(id => allowed.has(id));
}
