import type { OutlineDelta, OutlineProgress } from "@/types/outline";

// A gap triggers a fresh snapshot; never concatenate data onto a different attempt.
export function applyOutlineDelta(current: OutlineProgress | null, delta: OutlineDelta):
  { value: OutlineProgress | null; refresh: boolean } {
  if (!current) return { value: current, refresh: true };
  if (delta.revision < current.revision) return { value: current, refresh: false };
  if (delta.operation_id === current.operation_id && delta.seq <= current.seq) return { value: current, refresh: false };
  const live = current.live;
  if (delta.revision !== current.revision || delta.operation_id !== current.operation_id ||
      delta.seq !== current.seq + 1 || !live || live.attempt !== delta.attempt ||
      live.segment_id !== delta.segment_id || Array.from(live.text).length !== delta.offset) {
    return { value: current, refresh: true };
  }
  return { value: { ...current, seq: delta.seq, live: { ...live, text: live.text + delta.text } }, refresh: false };
}


// A slow REST response from the previous answer must not replace a newer SSE operation.
export function applyOutlineSnapshot(current: OutlineProgress | null, incoming: OutlineProgress): OutlineProgress {
  if (!current) return incoming;
  if (incoming.revision < current.revision) return current;
  if (incoming.revision === current.revision) {
    if (incoming.operation_id === current.operation_id && incoming.seq < current.seq) return current;
    if (incoming.operation_created_at && current.operation_created_at &&
        incoming.operation_created_at < current.operation_created_at) return current;
  }
  return incoming;
}
