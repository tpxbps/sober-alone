/** One ordering rule for HTTP snapshots and SSE, scoped to an operation. */
export class OperationOrder {
  private sequences = new Map<string, number>();
  accept(channel: string, sequence?: number): boolean {
    const next = sequence ?? 0;
    const previous = this.sequences.get(channel) ?? -1;
    if (next <= previous) return false;
    this.sequences.set(channel, next);
    return true;
  }
}
