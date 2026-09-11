import React, { useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Character, PublicClue } from "@/types/game";
import { ClueCitationHover } from "../game/ClueCitationHover";

const NO_CHARACTERS: Character[] = [];
const NO_CLUES: PublicClue[] = [];

interface GameMessageMarkdownProps {
  children: string;
  className?: string;
  /** 角色名称列表，用于高亮匹配 */
  characters?: Character[];
  /** 是否保留原始空白符（换行等），用于真人玩家发言 */
  preserveWhitespace?: boolean;
  publicClues?: PublicClue[];
}

const CLUE_ID_SOURCE = String.raw`(?:c[0-9]{2,4})|(?:clue-[a-z0-9]{12})`;
const clueTagPattern = () => new RegExp(`\\[(${CLUE_ID_SOURCE})\\]`, "gi");
const clueCodeTagPattern = () =>
  new RegExp("`+\\s*\\[(" + CLUE_ID_SOURCE + ")\\]\\s*`+", "gi");
const clueMarkdownLinkPattern = () =>
  new RegExp(
    "`*\\\\?\\[[^\\]\\n]{1,200}\\\\?\\]\\s*\\\\?\\(\\s*#clue-ref-(" +
      CLUE_ID_SOURCE +
      ")\\s*\\\\?\\)`*",
    "gi",
  );
const clueBareIdPattern = () =>
  new RegExp(
    "(?<![\\w\\[#/-])(" + CLUE_ID_SOURCE + ")(?![\\w\\]-])",
    "gi",
  );
const CLUE_LINK_PREFIX = "#clue-ref-";

function normalizeClueSyntax(content: string, clueMap: Map<string, PublicClue>) {
  const canonicalizeVariant = (original: string, id: string) => {
    const normalizedId = id.toLowerCase();
    return clueMap.has(normalizedId) ? `[${normalizedId}]` : original;
  };
  let normalized = content.replace(clueCodeTagPattern(), canonicalizeVariant);
  normalized = normalized.replace(clueMarkdownLinkPattern(), canonicalizeVariant);

  const explicitIds = new Set(
    Array.from(normalized.matchAll(clueTagPattern()), (match) => match[1].toLowerCase()).filter(
      (id) => clueMap.has(id),
    ),
  );
  return normalized.replace(clueBareIdPattern(), (original, id: string) => {
    const normalizedId = id.toLowerCase();
    if (!clueMap.has(normalizedId)) return original;
    return explicitIds.has(normalizedId) ? "" : `[${normalizedId}]`;
  });
}

function escapeMarkdownLabel(value: string) {
  return value
    .replaceAll("\\", "\\\\")
    .replaceAll("[", "\\[")
    .replaceAll("]", "\\]");
}

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
}: GameMessageMarkdownProps) {
  // Normalize mentions, keep clue references at their exact sentence position,
  // and only activate IDs that the server says have already been revealed.
  const clueMap = useMemo(() => new Map(publicClues.map((clue) => [clue.id.toLowerCase(), clue])), [publicClues]);
  const contentWithCompatibilityRefs = normalizeClueSyntax(
    children.replace(/@{2,}/g, "@"),
    clueMap,
  );
  const normalizedContent = contentWithCompatibilityRefs
    .replace(clueTagPattern(), (tag, id: string) => {
      const normalizedId = id.toLowerCase();
      const clue = clueMap.get(normalizedId);
      if (!clue) return tag;
      return `[${escapeMarkdownLabel(clue.summary)}](${CLUE_LINK_PREFIX}${encodeURIComponent(normalizedId)})`;
    })
    .trim();

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
          a: ({ href, children }) => {
            if (href?.startsWith(CLUE_LINK_PREFIX)) {
              const clueId = decodeURIComponent(href.slice(CLUE_LINK_PREFIX.length)).toLowerCase();
              const clue = clueMap.get(clueId);
              if (clue) return <ClueCitationHover clue={clue} />;
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
        }), [characters, clueMap]);

  return (
    <div
      className={`markdown-content relative max-w-none break-words ${
        preserveWhitespace ? "whitespace-pre-wrap" : ""
      } ${className || ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
