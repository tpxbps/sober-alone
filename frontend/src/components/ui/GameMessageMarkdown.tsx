import React, { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface GameMessageMarkdownProps {
  children: string;
  className?: string;
  /** 角色名称列表，用于高亮匹配 */
  characterNames?: string[];
  /** 是否保留原始空白符（换行等），用于真人玩家发言 */
  preserveWhitespace?: boolean;
}

/**
 * 渲染带有角色名称高亮的文本
 * 处理@前缀的"多退少补"：如果已有@则不添加，没有则添加
 */
function renderTextWithHighlights(
  text: string,
  characterNames: string[]
): ReactNode {
  if (!text || characterNames.length === 0) return text;

  // 清理并按长度降序排序，避免短名称被长名称的部分匹配
  const cleanedNames = characterNames.map((n) => n.trim()).filter(Boolean);
  if (cleanedNames.length === 0) return text;

  const sortedNames = [...cleanedNames].sort((a, b) => b.length - a.length);

  // 创建匹配 @?角色名称 的正则（按长度降序）
  // 匹配可选的@后跟角色名称
  const escapedNames = sortedNames.map((n) =>
    n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  // 匹配 @名字 或 名字（前面没有@）
  const pattern = new RegExp(`@?(${escapedNames.join("|")})`, "g");

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

    const matchedText = match[0]; // 可能是 "@名字" 或 "名字"
    const name = match[1]; // 只是名字部分

    if (nameSet.has(name)) {
      // 统一显示为 @名字 格式（高亮）
      result.push(
        <span
          key={result.length}
          className="text-primary font-medium bg-primary/10 px-1 rounded"
        >
          @{name}
        </span>
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
  characterNames: string[]
): React.ReactNode {
  if (typeof children === "string") {
    return renderTextWithHighlights(children, characterNames);
  }

  if (Array.isArray(children)) {
    return children.map((child, index) => {
      if (typeof child === "string") {
        return (
          <React.Fragment key={index}>
            {renderTextWithHighlights(child, characterNames)}
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
            characterNames
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
  characterNames = [],
  preserveWhitespace = false,
}: GameMessageMarkdownProps) {
  // Normalize double/multiple @ into a single @ before rendering
  const normalizedContent = children.replace(/@{2,}/g, "@");

  return (
    <div
      className={`markdown-content max-w-none break-words overflow-hidden ${
        preserveWhitespace ? "whitespace-pre-wrap" : ""
      } ${className || ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 自定义段落渲染 - 在这里处理角色名称高亮
          p: ({ children }) => (
            <p className="mb-1 last:mb-0 leading-relaxed">
              {processChildrenWithHighlights(children, characterNames)}
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
              {processChildrenWithHighlights(children, characterNames)}
            </li>
          ),
          // 自定义强调渲染
          strong: ({ children }) => (
            <strong className="font-bold text-primary">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
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
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
