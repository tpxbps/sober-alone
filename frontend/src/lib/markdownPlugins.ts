import type { Nodes, PhrasingContent, Root, Text } from "mdast";
import type { Options } from "react-markdown";
import remarkCjkFriendly from "remark-cjk-friendly/parseOnly";
import remarkGfm from "remark-gfm";

/** Tolerate padded strong markers only in otherwise literal, unescaped text. */
function remarkPaddedStrong() {
  return (tree: Root, file: { value: unknown }) => {
    const source = String(file.value);

    function splitText(node: Text): PhrasingContent[] {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      // Escapes/entities have already been decoded by Markdown. Leave those
      // nodes alone rather than interpreting deliberately literal asterisks.
      if (start === undefined || end === undefined || source.slice(start, end) !== node.value) {
        return [node];
      }
      const parts: PhrasingContent[] = [];
      let cursor = 0;
      const pattern = /(?<![*\\])\*\*([^*\n\r`_[\]<>]+)\*\*(?!\*)/g;
      for (const match of node.value.matchAll(pattern)) {
        const inner = match[1];
        if (!/^[ \t]|[ \t]$/.test(inner) || !inner.trim()) continue;
        parts.push({ type: "text", value: node.value.slice(cursor, match.index) });
        parts.push({ type: "strong", children: [{ type: "text", value: inner.trim() }] });
        cursor = match.index + match[0].length;
      }
      if (!cursor) return [node];
      parts.push({ type: "text", value: node.value.slice(cursor) });
      return parts;
    }

    function walk(node: Nodes) {
      if (!("children" in node)) return;
      // Do not reinterpret nested emphasis or link labels/destinations.
      if (["strong", "emphasis", "link", "linkReference"].includes(node.type)) return;
      for (let i = 0; i < node.children.length; i += 1) {
        const child = node.children[i];
        if (child.type === "text") {
          const parts = splitText(child);
          node.children.splice(i, 1, ...parts);
          i += parts.length - 1;
        } else {
          walk(child);
        }
      }
    }
    walk(tree);
  };
}

// Stable identities also preserve DOM selection during audio progress updates.
export const markdownPlugins: Options["remarkPlugins"] = [
  remarkGfm,
  remarkCjkFriendly,
  remarkPaddedStrong,
];
