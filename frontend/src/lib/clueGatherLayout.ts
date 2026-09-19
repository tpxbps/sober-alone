/** Viewport-relative, bounded photograph layouts shared by desktop and phone. */
export function clueGatherLayout(index: number, count: number, mobile: boolean) {
  const double = count > 8;
  const firstRow = double ? Math.ceil(count / 2) : count;
  const row = double && index >= firstRow ? 1 : 0;
  const size = row ? count - firstRow : firstRow;
  const local = row ? index - firstRow : index;
  const t = size <= 1 ? 0 : (local / (size - 1) - 0.5) * 2;
  return {
    x: t * (mobile ? 26 : 31),
    y: (double ? (row ? 10 : -14) : -5) + t * t * (double ? 3 : 7),
    angle: t * (mobile ? 9 : 12),
    scale: double ? (mobile ? 0.24 : 0.21) : (mobile ? 0.27 : 0.24),
  };
}
