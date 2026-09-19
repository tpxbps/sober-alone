import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { CluePresentationState } from '@/types/cluePresentation';

class TestImage {
  static requests: TestImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = '';
  decode = vi.fn(() => Promise.resolve());
  constructor() { TestImage.requests.push(this); }
}
beforeEach(() => {
  vi.resetModules(); vi.useFakeTimers(); TestImage.requests = [];
  vi.stubGlobal('Image', TestImage);
  vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('deduplicates warmup/render/replay and only publishes a decoded image', async () => {
  const { loadClueImage } = await import('./clueImageLoader');
  const first = loadClueImage('/images/a.webp');
  expect(loadClueImage('/images/a.webp')).toBe(first);
  const image = TestImage.requests[0];
  let decoded!: () => void;
  image.decode.mockImplementation(() => new Promise<void>(resolve => { decoded = resolve; }));
  let ready = false;
  void first.then(() => { ready = true; });
  image.onload!(); await Promise.resolve();
  expect(ready).toBe(false);
  decoded(); expect(await first).toBe(true);
  image.decode.mockResolvedValue();
  expect(await loadClueImage('/images/a.webp')).toBe(true);
  expect(TestImage.requests).toHaveLength(1);
});

it('bounds concurrency, times out stalled requests and allows a later retry', async () => {
  const { loadClueImage } = await import('./clueImageLoader');
  const pending = Array.from({ length: 5 }, (_, i) => loadClueImage(`/images/${i}.webp`));
  expect(TestImage.requests).toHaveLength(3);
  TestImage.requests[0].onerror!();
  expect(TestImage.requests).toHaveLength(4);
  await vi.advanceTimersByTimeAsync(24000);
  expect(await Promise.all(pending)).toEqual([false, false, false, false, false]);
  expect(TestImage.requests).toHaveLength(5);
  expect(await loadClueImage('/images/0.webp')).toBe(false);
  await vi.advanceTimersByTimeAsync(7000);
  const retry = loadClueImage('/images/0.webp');
  TestImage.requests.at(-1)!.onload!();
  expect(await retry).toBe(true);
});

it('warms only the active presentation and its referenced public images', async () => {
  const { presentationMedia, warmCluePresentation, loadClueImage } = await import('./clueImageLoader');
  const media = (name: string) => ({ status: 'ready', image_url: `/images/${name}.webp`, thumbnail_url: `/images/${name}-thumb.webp` });
  const state = { status: 'pending', presentation: { status: 'ready', background: media('bg'), shots: [{ clue_ids: ['old', 'current'] }] },
    clues: [{ id: 'current', media: media('current') }], reference_clues: [
      { id: 'old', media: media('old') }, { id: 'current', media: media('current') }, { id: 'unused', media: media('unused') },
    ] } as unknown as CluePresentationState;
  expect(presentationMedia(state).map(item => item.image_url)).toEqual(['/images/bg.webp', '/images/old.webp', '/images/current.webp']);
  expect(await warmCluePresentation({ ...state, status: 'acknowledged' })).toEqual([]);
  expect(await loadClueImage('https://other.example/image.webp')).toBe(false);
  expect(TestImage.requests).toHaveLength(0);
});
