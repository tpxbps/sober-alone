import type { ClueMedia, CluePresentationState } from '@/types/cluePresentation';

type Entry = { promise: Promise<boolean>; settled: boolean; failedAt?: number; image?: HTMLImageElement };
const cache = new Map<string, Entry>();
const queue: (() => void)[] = [];
let active = 0;

function drain() {
  while (active < 3 && queue.length) queue.shift()!();
}

/** Shared, bounded loading/decode queue. Prefetch never holds up game actions. */
export function loadClueImage(url: string): Promise<boolean> {
  if (typeof Image === 'undefined' || !/^\/images\/[^?#]+$/.test(url) || url.includes('..')) return Promise.resolve(false);
  const cached = cache.get(url);
  if (cached && (!cached.failedAt || Date.now() - cached.failedAt < 30000)) {
    if (cached.failedAt) return Promise.resolve(false);
    // A browser may discard decoded pixels during a long discussion; check again before play.
    if (cached.settled && !cached.failedAt && cached.image) return cached.image.decode().then(
      () => true, () => { cached.failedAt = Date.now(); return false; });
    return cached.promise;
  }
  let resolve!: (loaded: boolean) => void;
  const entry: Entry = {
    promise: new Promise<boolean>(done => { resolve = done; }), settled: false,
  };
  cache.set(url, entry);
  queue.push(() => {
    active++;
    const image = new Image();
    entry.image = image;
    image.decoding = 'async';
    image.fetchPriority = 'low';
    const finish = (loaded: boolean) => {
      if (entry.settled) return;
      entry.settled = true;
      if (!loaded) entry.failedAt = Date.now();
      clearTimeout(timeout);
      image.onload = image.onerror = null;
      resolve(loaded);
      active--;
      // Bound retained images across games while keeping current/next rounds warm.
      for (const [key, value] of cache) {
        if (cache.size <= 24) break;
        if (value.settled) cache.delete(key);
      }
      drain();
    };
    const timeout = setTimeout(() => { image.src = ''; finish(false); }, 12000);
    image.onload = () => { void image.decode().then(() => finish(true), () => finish(false)); };
    image.onerror = () => finish(false);
    image.src = url;
  });
  drain();
  return entry.promise;
}

/** Full images required for this presentation, in playback order. */
export function presentationMedia(state?: CluePresentationState | null): ClueMedia[] {
  if (!state?.presentation || state.presentation.status !== 'ready'
    || !Array.isArray(state.presentation.shots) || !Array.isArray(state.clues)
    || (state.reference_clues != null && !Array.isArray(state.reference_clues))) return [];
  const clues = new Map((state.reference_clues ?? state.clues).map(clue => [clue.id, clue]));
  const media = [state.presentation.background,
    ...state.presentation.shots.flatMap(shot => Array.isArray(shot?.clue_ids) ? shot.clue_ids.map(id => clues.get(id)?.media) : []),
    ...state.clues.map(clue => clue.media)];
  return [...new Map(media.filter((item): item is ClueMedia => item?.status === 'ready')
    .map(item => [item.image_url, item])).values()];
}

export function warmClueAssets(urls?: string[], retry = false): Promise<boolean[]> {
  if (typeof window === 'undefined' || !Array.isArray(urls)
    || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return Promise.resolve([]);
  if (retry) for (const url of urls) if (cache.get(url)?.failedAt) cache.delete(url);
  return Promise.all([...new Set(urls)].map(loadClueImage));
}

export function warmCluePresentation(state?: CluePresentationState | null, retry = false): Promise<boolean[]> {
  if (state?.status !== 'pending' || typeof window === 'undefined'
    || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return Promise.resolve([]);
  return warmClueAssets(presentationMedia(state).map(media => media.image_url), retry);
}
