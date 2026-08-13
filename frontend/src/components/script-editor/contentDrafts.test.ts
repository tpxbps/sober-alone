import { describe, expect, it } from "vitest";

import type { EditorInterruptInfo, GameDataSections } from "@/types/editor";
import { cloneGameDataSections, workflowDraftKey } from "./contentDrafts";

const gameData: GameDataSections = {
  opening: "开场",
  clue_stages: [],
  truth_reveal: "真相",
  full_truth: "完整真相",
  game_flow: [{ type: "initial", system_notice: "原始通知" }],
  free_speech_limits: [1, 1],
  character_scripts: { 林岚: "原始个人剧本" },
  character_data: [
    {
      name: "林岚",
      profile: "气象观察员",
      appearance: "深色雨衣",
      system_prompt: "保持角色秘密",
    },
  ],
};

describe("ContentPanel draft isolation", () => {
  it("deep-clones nested game data before editing", () => {
    const cloned = cloneGameDataSections(gameData)!;

    cloned.game_flow[0].system_notice = "编辑后的通知";
    cloned.character_scripts["林岚"] = "编辑后的个人剧本";
    cloned.character_data[0].profile = "编辑后的简介";

    expect(gameData.game_flow[0].system_notice).toBe("原始通知");
    expect(gameData.character_scripts["林岚"]).toBe("原始个人剧本");
    expect(gameData.character_data[0].profile).toBe("气象观察员");
  });

  it("keys drafts by checkpoint or interrupt identity", () => {
    const interrupt: EditorInterruptInfo = {
      step: "review_final",
      step_label: "终稿审阅",
      generated_content: "第一版终稿",
      prompt_used: "提示词",
    };

    expect(workflowDraftKey("review_final", interrupt)).not.toBe(
      workflowDraftKey("review_final", {
        ...interrupt,
        generated_content: "第二版终稿",
      })
    );
    expect(workflowDraftKey("review_final", interrupt, "cp-1")).toBe(
      "checkpoint:cp-1"
    );
  });
});

