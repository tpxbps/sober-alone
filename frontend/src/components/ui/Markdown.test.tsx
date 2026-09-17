import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";
import { GameMessageMarkdown } from "./GameMessageMarkdown";

for (const Component of [Markdown, GameMessageMarkdown]) {
  describe(`${Component === Markdown ? "Markdown" : "GameMessageMarkdown"} emphasis`, () => {
    const render = (text: string) => renderToStaticMarkup(<Component>{text}</Component>);

    it.each(["这是真的吗？", "我记得。", "他说：“别走。”", "记录（未确认）"])(
      "renders CJK punctuation next to surrounding text: %s",
      (text) => {
        expect(render(`之前**${text}**之后`)).toMatch(new RegExp(`<strong[^>]*>${text}</strong>`));
      },
    );

    it("tolerates simple padded strong text without changing surrounding spaces", () => {
      const markup = render("之前 ** xxx? ** 之后，** 中文？ **紧接中文。");
      expect(markup).toMatch(/之前 <strong[^>]*>xxx\?<\/strong> 之后/);
      expect(markup).toMatch(/<strong[^>]*>中文？<\/strong>紧接中文/);
      expect(markup).not.toContain("**");
    });

    it("preserves lists, nested emphasis, links and GFM", () => {
      const markup = render("- **20:00—20:10**：经过。\n- **重要的*细节***\n\n[原文](https://example.com) ~~旧说法~~");
      expect(markup).toContain("<ul");
      expect(markup).toMatch(/<strong[^>]*>20:00—20:10<\/strong>/);
      expect(markup).toMatch(/<em[^>]*>细节<\/em>/);
      expect(markup).toContain('href="https://example.com"');
      expect(markup).toContain("<del>旧说法</del>");
    });

    it.each([
      "`** padded? **`",
      "```text\n** padded? **\n```",
      String.raw`\*\* padded? \*\*`,
      "还没写完 ** padded?",
      "**   **",
      "[** label? **](https://example.com)",
      "** first\nsecond **",
    ])("does not reinterpret code, escapes, links or incomplete text: %s", (text) => {
      expect(render(text)).not.toContain("<strong");
    });

    it("does not enable HTML or unsafe links", () => {
      const markup = render('<img src=x onerror="alert(1)">\n\n[点击](javascript:alert%281%29)');
      expect(markup).not.toContain("<img");
      expect(markup).not.toContain('href="javascript:');
    });
  });
}
