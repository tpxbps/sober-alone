import { describe, expect, it } from "vitest";

import { STEP_VOICE_GROUPS, STEP_VOICE_OPTIONS } from "./stepVoices";

describe("step voice options", () => {
  it("exposes the complete male and female voice catalog", () => {
    expect(STEP_VOICE_GROUPS.map((group) => group.voices.length)).toEqual([9, 18]);
    expect(STEP_VOICE_OPTIONS).toHaveLength(27);
    expect(STEP_VOICE_OPTIONS.map((voice) => voice.id)).toContain("cixingnansheng");
    expect(STEP_VOICE_OPTIONS.map((voice) => voice.id)).toContain("wenroushunv");
  });

  it("does not expose duplicate voice ids", () => {
    const ids = STEP_VOICE_OPTIONS.map((voice) => voice.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
