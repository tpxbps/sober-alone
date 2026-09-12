import { describe, expect, it } from "vitest";
import { applyOutlineDelta, applyOutlineSnapshot } from "./outlineStream";
import type { OutlineProgress } from "@/types/outline";

const base = {
  operation_id: "one", revision: 2, seq: 3,
  session: { revision: 2 }, control: {},
  live: { segment_id: "opening", attempt: "a", text: "雾🌫" },
} as OutlineProgress;
const delta = { operation_id: "one", revision: 2, seq: 4, segment_id: "opening", attempt: "a", offset: 2, text: "港" };

describe("outline stream recovery", () => {
  it("uses Unicode character offsets and ignores duplicate deliveries", () => {
    const result = applyOutlineDelta(base, delta);
    expect(result.value?.live?.text).toBe("雾🌫港");
    expect(applyOutlineDelta(result.value, delta).value).toBe(result.value);
  });
  it("refreshes on missing chunks or a changed attempt", () => {
    expect(applyOutlineDelta(base, { ...delta, seq: 5 }).refresh).toBe(true);
    expect(applyOutlineDelta(base, { ...delta, attempt: "b" }).refresh).toBe(true);
    expect(applyOutlineDelta(null, delta).refresh).toBe(true);
  });
  it("never appends abandoned version output", () => {
    expect(applyOutlineDelta(base, { ...delta, revision: 1 })).toEqual({ value: base, refresh: false });
  });
});


it("rejects an earlier answer snapshot arriving after the next operation started", () => {
  const current = { ...base, operation_id: "answer-2", operation_created_at: "2026-09-12T00:01:00.000000" };
  const stale = { ...base, operation_id: "answer-1", seq: 900, operation_created_at: "2026-09-12T00:00:00.000000" };
  expect(applyOutlineSnapshot(current, stale)).toBe(current);
  expect(applyOutlineSnapshot(current, { ...stale, revision: 3 }).revision).toBe(3);
});
