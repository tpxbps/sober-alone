import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GameMessageMarkdown } from "./GameMessageMarkdown";

const characters = [
  {
    character_id: "c1",
    script_id: "script",
    name: "林岚",
    can_manage: false,
  },
];

describe("GameMessageMarkdown mentions", () => {
  it("highlights ordinary names without adding @ and renders explicit mentions as chips", () => {
    const ordinary = renderToStaticMarkup(
      <GameMessageMarkdown characters={characters}>林岚刚才离开过。</GameMessageMarkdown>
    );
    const mentioned = renderToStaticMarkup(
      <GameMessageMarkdown characters={characters}>@林岚 请解释。</GameMessageMarkdown>
    );

    expect(ordinary.replace(/<[^>]+>/g, "")).toContain("林岚刚才离开过");
    expect(ordinary).toContain('data-character-name="林岚"');
    expect(ordinary).not.toContain("@林岚");
    expect(mentioned).toContain("@林岚");
    expect(mentioned).toContain('data-mention-name="林岚"');
  });
});
