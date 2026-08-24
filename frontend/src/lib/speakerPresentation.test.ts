import { describe, expect, it } from "vitest";

import { resolveDisplayedSpeakerId } from "./speakerPresentation";

describe("resolveDisplayedSpeakerId", () => {
  it("hides a queued AI while free-discussion auto speak is paused", () => {
    expect(
      resolveDisplayedSpeakerId({
        stage: "free_discussion",
        isAutoSpeakPaused: true,
        isStreaming: false,
        streamingSpeakerId: null,
        currentSpeakerId: "ai-next",
      })
    ).toBeNull();
  });

  it("keeps the active AI highlighted when pausing after streaming started", () => {
    expect(
      resolveDisplayedSpeakerId({
        stage: "free_discussion",
        isAutoSpeakPaused: true,
        isStreaming: true,
        streamingSpeakerId: "ai-speaking",
        currentSpeakerId: "ai-speaking",
      })
    ).toBe("ai-speaking");
  });

  it("shows the queued speaker when auto speak is not paused", () => {
    expect(
      resolveDisplayedSpeakerId({
        stage: "free_discussion",
        isAutoSpeakPaused: false,
        isStreaming: false,
        streamingSpeakerId: null,
        currentSpeakerId: "ai-next",
      })
    ).toBe("ai-next");
  });
});
