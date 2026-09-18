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

  it("renders only complete known clue tags as citation controls", () => {
    const clue = {
      id: "c01",
      summary: "门锁痕迹",
      content: "门锁没有撬动痕迹。",
      stage: 1,
    };
    const markup = renderToStaticMarkup(
      <GameMessageMarkdown publicClues={[clue]} allowedCitationIds={[clue.id]}>
        第一句没有依据。第二句是熟人作案。[c01] 第三句仍然可见。[c99]
      </GameMessageMarkdown>
    );

    expect(markup).toContain("查看线索 门锁痕迹");
    expect(markup).not.toContain("[c01]");
    expect(markup).toContain("[c99]");
    expect(markup.indexOf("第二句是熟人作案")).toBeLessThan(
      markup.indexOf("查看线索 门锁痕迹"),
    );
    expect(markup.indexOf("查看线索 门锁痕迹")).toBeLessThan(
      markup.indexOf("第三句仍然可见"),
    );
    expect(markup).not.toContain("c01</code>");
  });

  it("repairs code-wrapped tags, internal links and unexplained bare IDs", () => {
    const clues = [
      { id: "c02", summary: "广播记录", content: "广播持续九秒。", stage: 1 },
      { id: "c04", summary: "设备记录", content: "服务器停用。", stage: 1 },
      { id: "c06", summary: "节目清单", content: "母带今晚销毁。", stage: 1 },
    ];
    const markup = renderToStaticMarkup(
      <GameMessageMarkdown publicClues={clues} allowedCitationIds={clues.map(clue => clue.id)}>
        {"c02 明确记录广播持续九秒。`[c02]`\n[设备](#clue-ref-c04) 显示异常。\n至于清单 c06，我需要解释。"}
      </GameMessageMarkdown>,
    );

    expect(markup).not.toContain("#clue-ref-");
    expect(markup).not.toContain("c02 明确");
    expect(markup).not.toContain("c06，我");
    expect(markup).toContain("查看线索 广播记录");
    expect(markup).toContain("查看线索 设备记录");
    expect(markup).toContain("查看线索 节目清单");
  });
});

it("does not retroactively activate an introduction's unknown citation", () => {
  const clue = { id: "c01", summary: "门锁", content: "完整证据", stage: 1 };
  const render = (clues: typeof clue[]) => renderToStaticMarkup(
    <GameMessageMarkdown publicClues={clues} allowedCitationIds={[]}>我是馆长。[c01]</GameMessageMarkdown>
  );
  for (const clues of [[], [clue]]) {
    const markup = render(clues);
    expect(markup).toContain("[c01]");
    expect(markup).not.toContain("查看线索");
  }
  const missingMetadata = renderToStaticMarkup(
    <GameMessageMarkdown publicClues={[clue]}>旧记录。[c01]</GameMessageMarkdown>
  );
  expect(missingMetadata).not.toContain("查看线索");
});

describe("attached clue evidence", () => {
  const clues = [
    { id: "c01", summary: "门锁", content: "没有撬痕", stage: 1 },
    { id: "c02", summary: "窗台", content: "留有泥土", stage: 1 },
  ];
  const render = (text: string) => renderToStaticMarkup(
    <GameMessageMarkdown publicClues={clues} allowedCitationIds={['c01', 'c02']}>
      {text}
    </GameMessageMarkdown>,
  );

  it("keeps inline Markdown and multiline reasoning with one evidence count", () => {
    const markup = render('[**门锁**完整，\n但窗台有泥土][c01，c02,c01]');
    expect(markup).toContain('查看 2 条引用线索');
    expect(markup).toContain('decoration-dashed');
    expect(markup).toContain('<strong');
    expect(markup).toContain('但窗台有泥土');
    expect(markup).not.toContain('查看线索 门锁');
  });

  it("does not hijack ordinary links with the generated fragment prefix", () => {
    const markup = render('[c01] [普通链接](#evidence-0) [别的链接](https://example.org)');
    expect(markup).toContain('查看线索 门锁');
    expect(markup).toContain('href="#evidence-0"');
    expect(markup).toContain('href="https://example.org"');
    expect(markup.match(/查看线索 门锁/g)).toHaveLength(1);
  });

  it("preserves code, escaped tags, and mixed invalid groups without clickable evidence", () => {
    for (const text of ['    [c01]', '```text\n[推理][c01,c02]\n```', '\\[c01]', '[推理][c01,c99]']) {
      const markup = render(text);
      expect(markup).not.toContain('查看线索');
      expect(markup).not.toContain('条引用线索');
      expect(markup).toContain('c01');
    }
  });
});
