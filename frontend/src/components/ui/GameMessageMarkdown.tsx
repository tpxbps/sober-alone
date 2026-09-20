import React, { useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { markdownPlugins } from "@/lib/markdownPlugins";
import type { Character, PublicClue } from "@/types/game";
import { trustedClueTokens, escapeClueLabel } from "@/lib/clueReferences";
import { ClueCitationHover } from "../game/ClueCitationHover";

const NO_CHARACTERS: Character[] = [];
const NO_CLUES: PublicClue[] = [];
const NO_IDS: string[] = [];

interface GameMessageMarkdownProps {
  children: string;
  className?: string;
  /** 角色名称列表，用于高亮匹配 */
  characters?: Character[];
  /** 是否保留原始空白符（换行等），用于真人玩家发言 */
  preserveWhitespace?: boolean;
  publicClues?: PublicClue[];
  /** Permission captured for this message; absent means no trusted citations. */
  allowedCitationIds?: string[];
}

const CLUE_LINK_PREFIX = "#evidence-";

/** 渲染普通角色名高亮和显式 @角色名引用。 */
function renderTextWithHighlights(
  text: string,
  characters: Character[]
): ReactNode {
  if (!text || characters.length === 0) return text;

  // 清理并按长度降序排序，避免短名称被长名称的部分匹配
  const cleanedNames = characters.map((item) => item.name.trim()).filter(Boolean);
  if (cleanedNames.length === 0) return text;

  const sortedNames = [...cleanedNames].sort((a, b) => b.length - a.length);

  const escapedNames = sortedNames.map((n) =>
    n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  const pattern = new RegExp(`(@?)(${escapedNames.join("|")})`, "g");

  // 用于快速查找的Set
  const nameSet = new Set(cleanedNames);

  const result: ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    // 添加匹配前的文本
    if (match.index > lastIndex) {
      result.push(text.slice(lastIndex, match.index));
    }

    const matchedText = match[0];
    const explicitMention = match[1] === "@";
    const name = match[2];

    if (nameSet.has(name)) {
      const character = characters.find((item) => item.name === name);
      result.push(
        explicitMention ? (
          <span
            key={result.length}
            data-mention-name={name}
            className="inline-flex items-center gap-1 text-primary font-medium bg-primary/10 px-1.5 py-0.5 rounded-full align-middle"
          >
            <span className="w-4 h-4 rounded-full overflow-hidden bg-primary/20 flex items-center justify-center text-[9px]">
              {character?.avatar_url ? (
                <img src={character.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : (
                name[0]
              )}
            </span>
            @{name}
          </span>
        ) : (
          <span
            key={result.length}
            data-character-name={name}
            className="text-primary font-semibold bg-primary/10 px-1 rounded"
          >
            {name}
          </span>
        )
      );
    } else {
      result.push(matchedText);
    }

    lastIndex = match.index + matchedText.length;
  }

  // 添加剩余文本
  if (lastIndex < text.length) {
    result.push(text.slice(lastIndex));
  }

  return result.length > 0 ? result : text;
}

/**
 * 处理React节点，对其中的文本进行角色名称高亮
 */
function processChildrenWithHighlights(
  children: React.ReactNode,
  characters: Character[]
): React.ReactNode {
  if (typeof children === "string") {
    return renderTextWithHighlights(children, characters);
  }

  if (Array.isArray(children)) {
    return children.map((child, index) => {
      if (typeof child === "string") {
        return (
          <React.Fragment key={index}>
            {renderTextWithHighlights(child, characters)}
          </React.Fragment>
        );
      }
      // 如果是React元素，递归处理其children
      if (child && typeof child === "object" && "props" in child) {
        const reactChild = child as React.ReactElement<{
          children?: React.ReactNode;
        }>;
        if (reactChild.props && reactChild.props.children) {
          const processedChildren = processChildrenWithHighlights(
            reactChild.props.children,
            characters
          );
          return React.cloneElement(
            reactChild,
            { key: index },
            processedChildren
          );
        }
      }
      return child;
    });
  }

  return children;
}

/**
 * 游戏消息Markdown组件
 * 支持markdown格式渲染，同时高亮显示角色名称
 */
export function GameMessageMarkdown({
  children,
  className,
  characters = NO_CHARACTERS,
  preserveWhitespace = false,
  publicClues = NO_CLUES,
  allowedCitationIds = NO_IDS,
}: GameMessageMarkdownProps) {
  // Normalize mentions, keep clue references at their exact sentence position,
  // and only activate IDs that the server says have already been revealed.
  const allowedKey = allowedCitationIds.map(id => id.toLowerCase()).sort().join("\n");
  const clueMap = useMemo(() => {
    const allowed = new Set(allowedKey.split("\n"));
    return new Map(publicClues.filter(clue => allowed.has(clue.id.toLowerCase()))
      .map(clue => [clue.id.toLowerCase(), clue]));
  }, [publicClues, allowedKey]);
  const citationTokens = useMemo(() => trustedClueTokens(children.replace(/@{2,}/g, "@"), new Set(clueMap.keys()), new Map([...clueMap].map(([id, clue]) => [id, clue.summary]))), [children, clueMap]);
  const { normalizedContent, citationPositions } = useMemo(() => {
    let content = '';
    const positions = new Map<number, number>();
    citationTokens.forEach((token, index) => {
      if (!token.ids) { content += token.raw; return; }
      positions.set(content.length, index);
      const label = token.label ?? escapeClueLabel(clueMap.get(token.ids[0])!.summary);
      content += `[${label}](${CLUE_LINK_PREFIX}${index})`;
    });
    return { normalizedContent: content, citationPositions: positions };
  }, [citationTokens, clueMap]);

  // Keep renderer identities stable while playback progress updates the parent.
  const components = useMemo<Components>(() => ({
          // 自定义段落渲染 - 在这里处理角色名称高亮
          p: ({ children }) => (
            <p className="mb-1 last:mb-0 leading-relaxed">
              {processChildrenWithHighlights(children, characters)}
            </p>
          ),
          // 自定义列表渲染
          ul: ({ children }) => (
            <ul className="list-disc pl-4 mb-1 mt-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-4 mb-1 mt-1">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="mb-0.5 leading-relaxed">
              {processChildrenWithHighlights(children, characters)}
            </li>
          ),
          // 自定义强调渲染
          strong: ({ children }) => (
            <strong className="font-bold text-primary">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ href, children, node }) => {
            if (href?.startsWith(CLUE_LINK_PREFIX)
              && citationPositions.get(node?.position?.start.offset ?? -1) === Number(href.slice(CLUE_LINK_PREFIX.length))) {
              const token = citationTokens[Number(href.slice(CLUE_LINK_PREFIX.length))];
              const clues = token?.ids?.map(id => clueMap.get(id)).filter((clue): clue is PublicClue => Boolean(clue)) ?? [];
              if (clues.length) return token.label !== undefined
                ? <ClueCitationHover clues={clues}>{children}</ClueCitationHover>
                : <ClueCitationHover clue={clues[0]} />;
              return <>{children}</>;
            }
            return (
              <a href={href} className="text-primary underline underline-offset-2">
                {children}
              </a>
            );
          },
          // 自定义代码渲染
          code: ({ className: codeClassName, children, ...props }) => {
            const isInline = !codeClassName;
            if (isInline) {
              return (
                <code
                  className="px-1.5 py-0.5 rounded bg-secondary/50 text-primary font-mono text-xs"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code
                className="block p-2 rounded bg-secondary/30 font-mono text-xs overflow-x-auto"
                {...props}
              >
                {children}
              </code>
            );
          },
          // 自定义引用渲染
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary/50 pl-3 italic text-muted-foreground my-1">
              {children}
            </blockquote>
          ),
          // 自定义标题渲染
          h1: ({ children }) => (
            <h1 className="text-lg font-bold mb-1">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-bold mb-1">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-bold mb-0.5">{children}</h3>
          ),
          // 处理换行 - 将 \n 转换为较小间距的换行
          br: () => <br className="leading-tight" />,
        }), [characters, clueMap, citationTokens, citationPositions]);

  return (
    <div
      className={`markdown-content relative max-w-none break-words ${
        preserveWhitespace ? "whitespace-pre-wrap" : ""
      } ${className || ""}`}
    >
      <ReactMarkdown
        remarkPlugins={markdownPlugins}
        components={components}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
