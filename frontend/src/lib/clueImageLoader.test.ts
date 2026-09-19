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

it('defers next-round work to idle time, fetches sequentially and stops on cancellation', async () => {
  const callbacks = new Map<number, () => void>();
  let sequence = 0;
  window.requestIdleCallback = vi.fn(callback => {
    callbacks.set(++sequence, callback as () => void); return sequence;
  });
  window.cancelIdleCallback = vi.fn(id => { callbacks.delete(id); });
  vi.stubGlobal('document', { hidden: false });
  const { prefetchClueAssets, loadClueImage } = await import('./clueImageLoader');
  const cancel = prefetchClueAssets(['/images/a.webp', '/images/b.webp', '/images/c.webp']);
  expect(TestImage.requests).toHaveLength(0);
  callbacks.get(1)!();
  expect(TestImage.requests).toHaveLength(1);
  TestImage.requests[0].onload!();
  await vi.advanceTimersByTimeAsync(0);
  expect(TestImage.requests).toHaveLength(1);
  expect(await loadClueImage('/images/a.webp')).toBe(true);
  expect(TestImage.requests).toHaveLength(1);
  callbacks.get(2)!();
  expect(TestImage.requests).toHaveLength(2);
  cancel();
  TestImage.requests[1].onload!();
  await vi.advanceTimersByTimeAsync(0);
  expect(window.requestIdleCallback).toHaveBeenCalledTimes(2);
});

it('supports browsers without idle callbacks and never starts hidden-page work', async () => {
  window.setTimeout = setTimeout;
  window.clearTimeout = clearTimeout;
  vi.stubGlobal('document', { hidden: false });
  const { prefetchClueAssets } = await import('./clueImageLoader');
  const cancel = prefetchClueAssets(['/images/a.webp']);
  cancel();
  await vi.advanceTimersByTimeAsync(1000);
  expect(TestImage.requests).toHaveLength(0);
  prefetchClueAssets(['/images/b.webp']);
  vi.stubGlobal('document', { hidden: true });
  await vi.advanceTimersByTimeAsync(1000);
  expect(TestImage.requests).toHaveLength(0);
});

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

function playbackState(): CluePresentationState {
  const media = (id: string) => ({ status: 'ready', image_url: `/images/${id}.webp`, thumbnail_url: `/images/${id}.webp` });
  return { status: 'pending', presentation: { status: 'ready', shots: [{ clue_ids: ['a', 'b'] }] },
    clues: [{ id: 'a', media: media('a') }, { id: 'b', media: media('b') }],
  } as unknown as CluePresentationState;
}

it('retries transient failures without fetching successful images again', async () => {
  const { prepareCluePresentation } = await import('./clueImageLoader');
  const ready = prepareCluePresentation(playbackState(), new AbortController().signal);
  TestImage.requests[0].onload!(); TestImage.requests[1].onerror!();
  await vi.advanceTimersByTimeAsync(300);
  expect(TestImage.requests.map(image => image.src)).toEqual(['/images/a.webp', '/images/b.webp', '/images/b.webp']);
  TestImage.requests[2].onload!();
  expect(await ready).toBe(true);
});

it('gives up after three failed requests and never treats partial readiness as playable', async () => {
  const { prepareCluePresentation } = await import('./clueImageLoader');
  const ready = prepareCluePresentation(playbackState(), new AbortController().signal);
  TestImage.requests[0].onload!(); TestImage.requests[1].onerror!();
  await vi.advanceTimersByTimeAsync(300);
  TestImage.requests[2].onerror!();
  await vi.advanceTimersByTimeAsync(900);
  TestImage.requests[3].onerror!();
  expect(await ready).toBe(false);
  expect(TestImage.requests).toHaveLength(4);
  await vi.advanceTimersByTimeAsync(30000);
  expect(TestImage.requests).toHaveLength(4);
});

it('bounds stalled decodes and cancels retry work when the presentation closes', async () => {
  const { prepareCluePresentation } = await import('./clueImageLoader');
  const controller = new AbortController();
  const ready = prepareCluePresentation(playbackState(), controller.signal);
  for (const image of TestImage.requests) { image.decode.mockImplementation(() => new Promise<void>(() => {})); image.onload!(); }
  await vi.advanceTimersByTimeAsync(15000);
  expect(await ready).toBe(false);
  const before = TestImage.requests.length;
  const aborted = prepareCluePresentation(playbackState(), controller.signal);
  controller.abort();
  expect(await aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(16000);
  // Already in-flight requests may settle, but cancellation must not enqueue retries.
  expect(TestImage.requests.length).toBeLessThanOrEqual(before + 2);
});

it('rejects a config whose current or referenced clue has lost its image', async () => {
  const { prepareCluePresentation } = await import('./clueImageLoader');
  const state = playbackState();
  delete state.clues[0].media;
  expect(await prepareCluePresentation(state, new AbortController().signal)).toBe(false);
  expect(TestImage.requests).toHaveLength(0);
});
