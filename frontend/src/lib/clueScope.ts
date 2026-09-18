import type { PublicClue } from '@/types/game';
import { trustedClueTokens } from './clueReferences';

export function speechClues(stage: string, clues: PublicClue[]): PublicClue[] {
  return ['clue_analysis', 'free_discussion', 'summary', 'vote', 'review', 'completed'].includes(stage)
    ? clues.map(clue => ({ ...clue })) : [];
}

export function citedIds(content: string, clues: PublicClue[]): string[] {
  const allowed = new Set(clues.map(clue => clue.id.toLowerCase()));
  return [...new Set(trustedClueTokens(content, allowed).flatMap(token => token.ids ?? []))];
}
