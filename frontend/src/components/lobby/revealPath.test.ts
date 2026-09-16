import { describe, expect, it } from 'vitest';
import { sampleRevealPath } from './revealPath';

describe('pointer reveal input path', () => {
  it('follows a coalesced corner instead of cutting diagonally across it', () => {
    const samples = sampleRevealPath([{ x:0,y:0 },{ x:72,y:0 },{ x:72,y:72 }]);
    expect(samples).toHaveLength(8);
    expect(samples.every(point => point.y===0 || point.x===72)).toBe(true);
    expect(samples[3]).toMatchObject({ x:72,y:0,dx:1,dy:0 });
    expect(samples[7]).toMatchObject({ x:72,y:72,dx:0,dy:1 });
  });
  it('bounds GPU work while always reaching the latest actual coordinate', () => {
    const path = Array.from({ length:100 },(_,i) => ({ x:i*25,y:Math.sin(i)*40 }));
    const samples = sampleRevealPath(path);
    expect(samples).toHaveLength(12);
    expect(samples.at(-1)).toMatchObject(path.at(-1)!);
    expect(samples.every(p => Number.isFinite(p.dx) && Number.isFinite(p.dy))).toBe(true);
  });
  it('does not keep painting a moving stroke for repeated stationary events', () => {
    expect(sampleRevealPath([{ x:20,y:30 },{ x:20,y:30 }])).toEqual([]);
    expect(sampleRevealPath([{ x:20,y:30 }])).toEqual([]);
    expect(sampleRevealPath([])).toEqual([]);
  });
});
