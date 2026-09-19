import type { Character } from '@/types/game';

/** Keep API originals compatible; choose small portraits only in the UI adapter. */
export function characterImages(character: Character): Character {
  const variants = [...(character.avatar_variants || [])].sort((a, b) => a.width - b.width);
  if (!variants.length) return character;
  return { ...character, avatar_url: variants[0].url,
    portrait_url: character.portrait_url && character.portrait_url !== character.avatar_url
      ? character.portrait_url : variants.at(-1)!.url };
}
