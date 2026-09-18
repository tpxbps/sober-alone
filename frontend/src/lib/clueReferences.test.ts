import { describe, expect, it } from 'vitest';
import fixture from '../../../fixtures/clue-citations.json';
import { trustedClueTokens, serializeClue } from './clueReferences';

describe('shared evidence protocol', () => {
  for (const test of fixture.cases) it(test.name, () => {
    const tokens = trustedClueTokens(test.input, new Set(fixture.allowed));
    expect([...new Set(tokens.flatMap(token => token.ids ?? []))]).toEqual(test.humanRefs);
    if (test.unknown.length) expect(tokens.map(token => token.raw).join('')).toBe(test.input);
  });
  it('escapes editor brackets and preserves newlines', () => {
    const tokens = trustedClueTokens(serializeClue('第一行[说明]\n第二行', ['c01', 'c02']), new Set(fixture.allowed));
    expect(tokens.filter(token => token.ids)).toHaveLength(1);
    expect(tokens.find(token => token.ids)?.ids).toEqual(['c01', 'c02']);
    expect(serializeClue(' ', ['c01', 'c02'])).toBe('[c01][c02]');
  });
});
