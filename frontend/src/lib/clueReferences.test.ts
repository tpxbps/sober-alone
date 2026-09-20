import { describe, expect, it } from 'vitest';
import fixture from '../../../fixtures/clue-citations.json';
import { trustedClueTokens, serializeClue } from './clueReferences';

describe('shared evidence protocol', () => {
  for (const test of fixture.cases) it(test.name, () => {
    const tokens = trustedClueTokens(test.input, new Set(fixture.allowed), new Map(Object.entries(fixture.names)));
    expect([...new Set(tokens.flatMap(token => token.ids ?? []))]).toEqual(test.humanRefs);
    if (test.unknown.length) expect(tokens.map(token => token.raw).join('')).toBe(test.input);
    else expect(tokens.map(token => token.ids
      ? token.label !== undefined ? `[${token.label}][${token.ids.join(',')}]` : token.ids.map(id => `[${id}]`).join('')
      : token.raw).join('').trim()).toBe(test.ai.trim());
  });
  it('escapes editor brackets and preserves newlines', () => {
    const tokens = trustedClueTokens(serializeClue('第一行[说明]\n第二行', ['c01', 'c02']), new Set(fixture.allowed));
    expect(tokens.filter(token => token.ids)).toHaveLength(1);
    expect(tokens.find(token => token.ids)?.ids).toEqual(['c01', 'c02']);
    expect(serializeClue(' ', ['c01', 'c02'])).toBe('[c01][c02]');
  });
  it('recovers deeply nested brackets without losing later tags', () => {
    const tokens = trustedClueTokens('['.repeat(1050) + '[c01]' + ']'.repeat(1050) + '。后续[c02]', new Set(fixture.allowed));
    expect(tokens.flatMap(token => token.ids ?? [])).toEqual(['c01', 'c02']);
  });
});
