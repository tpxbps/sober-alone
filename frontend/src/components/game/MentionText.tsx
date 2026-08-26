import type { ReactNode } from "react";
import type { Character } from "@/types/game";

export function MentionText({ text, characters }: { text: string; characters: Character[] }) {
  const byName = new Map(characters.map((character) => [character.name, character]));
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  if (!names.length) return text;
  const escaped = names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`@(${escaped.join("|")})`, "g");
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(text.slice(cursor, index));
    const character = byName.get(match[1]);
    parts.push(
      <span key={`${index}-${match[1]}`} className="inline-flex items-center gap-1 mx-0.5 px-1.5 py-0.5 rounded-full bg-primary/15 text-primary align-middle">
        <span className="w-4 h-4 rounded-full overflow-hidden bg-primary/20 flex items-center justify-center text-[9px]">
          {character?.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : match[1][0]}
        </span>
        @{match[1]}
      </span>
    );
    cursor = index + match[0].length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
