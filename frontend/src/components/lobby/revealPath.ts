export type RevealPoint = { x: number; y: number };
export type RevealSample = RevealPoint & { dx: number; dy: number; distance: number };

/** Resample the actual event path in the current frame, including its last point.
 * A single per-frame budget bounds GPU splats even with coalesced pointer events.
 */
export function sampleRevealPath(points: readonly RevealPoint[], spacing = 18, limit = 12): RevealSample[] {
  const segments = points.slice(1).map((point, i) => {
    const from = points[i], dx = point.x - from.x, dy = point.y - from.y;
    return { from, point, dx, dy, length: Math.hypot(dx, dy) };
  }).filter(segment => segment.length > .01);
  const length = segments.reduce((sum, segment) => sum + segment.length, 0);
  if (length < .5 || !segments.length) return [];
  const count = Math.min(limit, Math.max(1, Math.ceil(length / spacing)));
  const samples: RevealSample[] = [];
  let index = 0, traversed = 0;
  for (let i = 1; i <= count; i++) {
    const target = length * i / count;
    while (index < segments.length - 1 && traversed + segments[index].length < target) {
      traversed += segments[index++].length;
    }
    const segment = segments[index];
    const t = Math.min(1, (target - traversed) / segment.length);
    samples.push({ x: segment.from.x + segment.dx * t, y: segment.from.y + segment.dy * t,
      dx: segment.dx / segment.length, dy: segment.dy / segment.length, distance: length / count });
  }
  // Keep the event coordinate exact; rounding may otherwise leave the tip behind.
  const last = points[points.length - 1];
  Object.assign(samples[samples.length - 1], last);
  return samples;
}
