/** Source tokenizer. Keep in sync with backend citation_syntax and shared fixtures. */
export const ID_SOURCE = '(?:c[0-9]{2,4}|clue-[a-z0-9]{12})';
const ID = new RegExp(`^${ID_SOURCE}$`, 'i');
export interface ClueToken { raw: string; ids?: string[]; label?: string; bare?: boolean }

function idsIn(value: string): string[] | undefined {
  const ids = value.trim().split(/[,，、;；\s]+/).filter(Boolean).map(id => id.toLowerCase());
  return ids.length && ids.every(id => ID.test(id)) ? [...new Set(ids)] : undefined;
}
function bracketEnd(text: string, start: number): number | undefined {
  let depth = 1;
  for (let i = start + 1; i < text.length; i++) {
    if (text[i] === '\\') { i++; continue; }
    if (text[i] === ']' && --depth === 0) return i + 1;
    if (text[i] === '[') depth++;
  }
}
export function tokenizeClues(content: string): ClueToken[] {
  const tokens: ClueToken[] = [];
  let cursor = 0;
  let plain = '';
  const flush = () => {
    if (!plain) return;
    let offset = 0;
    const bare = new RegExp(`(?<![a-z0-9_\\[#/\\\\-])(${ID_SOURCE})(?![a-z0-9_\\]-])`, 'gi');
    for (const m of plain.matchAll(bare)) {
      tokens.push({ raw: plain.slice(offset, m.index) }, { raw: m[0], ids: [m[1].toLowerCase()], bare: true });
      offset = m.index + m[0].length;
    }
    tokens.push({ raw: plain.slice(offset) });
    plain = '';
  };
  while (cursor < content.length) {
    const rest = content.slice(cursor);
    if ((cursor === 0 || content[cursor - 1] === '\n') && /^(?: {4}|\t)/.test(rest)) {
      flush(); const newline = content.indexOf('\n', cursor);
      const end = newline < 0 ? content.length : newline + 1;
      tokens.push({ raw: content.slice(cursor, end) }); cursor = end; continue;
    }
    if (rest[0] === '\\' && rest.length > 1) {
      flush(); tokens.push({ raw: rest.slice(0, 2) }); cursor += 2; continue;
    }
    const fence = rest.match(/^(`{3,}|~{3,})/);
    if (fence) {
      flush(); const close = content.indexOf(fence[0], cursor + fence[0].length);
      const end = close < 0 ? content.length : close + fence[0].length;
      tokens.push({ raw: content.slice(cursor, end) }); cursor = end; continue;
    }
    if (rest[0] === '`') {
      const marker = rest.match(/^`+/)![0];
      const end = content.indexOf(marker, cursor + marker.length);
      if (end >= 0) {
        flush(); const inside = content.slice(cursor + marker.length, end).trim();
        const old = inside.match(new RegExp(`^\\[(${ID_SOURCE})\\]$`, 'i'));
        tokens.push({ raw: content.slice(cursor, end + marker.length), ids: old ? [old[1].toLowerCase()] : undefined });
        cursor = end + marker.length; continue;
      }
      flush(); tokens.push({ raw: rest }); break;
    }
    if (rest[0] === '[') {
      const end = bracketEnd(content, cursor);
      if (end !== undefined) {
        const label = content.slice(cursor + 1, end - 1);
        const link = content.slice(end).match(/^\((?:\\.|[^)\n])*\)/);
        if (link) {
          flush(); const legacy = link[0].match(new RegExp(`^\\(\\s*#clue-ref-(${ID_SOURCE})\\s*\\)$`, 'i'));
          tokens.push({ raw: content.slice(cursor, end + link[0].length), ids: legacy ? [legacy[1].toLowerCase()] : undefined });
          cursor = end + link[0].length; continue;
        }
        if (content[end] === '[' && !idsIn(label)) {
          let groupEnd = end;
          const ids: string[] = [];
          while (content[groupEnd] === '[') {
            const nextEnd = bracketEnd(content, groupEnd);
            const groupIds = nextEnd ? idsIn(content.slice(groupEnd + 1, nextEnd - 1)) : undefined;
            if (!groupIds) break;
            ids.push(...groupIds.filter(id => !ids.includes(id)));
            groupEnd = nextEnd!;
          }
          if (ids.length && label.trim()) {
            flush(); tokens.push({ raw: content.slice(cursor, groupEnd), ids, label }); cursor = groupEnd!; continue;
          }
        }
        flush();
        if (!idsIn(label) && label.includes('[')) {
          tokens.push({ raw: '[' }); cursor++; continue;
        }
        tokens.push({ raw: content.slice(cursor, end), ids: idsIn(label) });
        cursor = end; continue;
      }
      plain += '['; cursor++; continue;
    }
    plain += content[cursor++];
  }
  flush();
  return tokens;
}

function labelParts(label: string, names: ReadonlyMap<string, string>): { label: string; ids: string[] } {
  const parts: string[] = [], ids: string[] = [];
  const pending = tokenizeClues(label).reverse();
  while (pending.length) {
    const token = pending.pop()!;
    if (!token.ids) { parts.push(token.raw); continue; }
    ids.push(...token.ids.filter(id => !ids.includes(id)));
    if (token.label !== undefined) {
      pending.push(...tokenizeClues(token.label).reverse());
    } else if (!token.bare) parts.push(...token.ids.map(id => escapeClueLabel(names.get(id) ?? '')));
  }
  return { label: parts.join(''), ids };
}

export function trustedClueTokens(content: string, allowed: Set<string>, names: ReadonlyMap<string, string> = new Map()): ClueToken[] {
  const tokens = tokenizeClues(content);
  return tokens.flatMap(token => {
    if (!token.ids) return [token];
    const nested = token.label !== undefined ? labelParts(token.label, names) : undefined;
    const ids = [...new Set([...token.ids, ...(nested?.ids ?? [])])];
    if (!ids.every(id => allowed.has(id))) return [{ raw: token.raw }];
    if (token.label === undefined && ids.length > 1) return ids.map(id => ({ raw: `[${id}]`, ids: [id] }));
    return [{ ...token, ids, ...(nested ? { label: nested.label } : {}) }];
  });
}
export function escapeClueLabel(value: string) {
  return value.replace(/\\/g, '\\\\').replace(/\[/g, '\\[').replace(/\]/g, '\\]');
}
export function serializeClue(label: string, ids: string[]) {
  return label.trim() ? `[${escapeClueLabel(label.trim())}][${ids.join(',')}]` : ids.map(id => `[${id}]`).join('');
}
