/** Retire optional GPU effects when sustained frame time makes input unresponsive. */
export class FrameBudget {
  private started = 0;
  private previous = 0;
  private frames = 0;
  private elapsed = 0;

  reset() { this.started = this.previous = this.frames = this.elapsed = 0; }

  exceeded(now: number) {
    if (!this.previous) { this.started = this.previous = now; return false; }
    const delta = Math.min(Math.max(now - this.previous, 0), 500);
    this.previous = now;
    // Ignore shader/font startup and do not let a single long task decide quality.
    if (now - this.started < 1200) return false;
    this.frames += 1;
    this.elapsed += delta;
    if (this.frames < 18) return false;
    const slow = this.elapsed / this.frames > 80;
    this.frames = this.elapsed = 0;
    return slow;
  }
}
