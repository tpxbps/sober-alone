import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, X, Lightbulb } from "lucide-react";

interface PlayerScriptTooltipProps {
  scriptContent: string;
  characterName?: string;
  sessionId?: string; // 用于持久化存储状态
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

// Simple markdown-like renderer for basic formatting
function renderMarkdownText(text: string) {
  // Handle bold text **text**
  let result = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Handle italic text *text*
  result = result.replace(/\*(.+?)\*/g, "<em>$1</em>");
  return result;
}

export function PlayerScriptTooltip({
  scriptContent,
  characterName,
  sessionId,
  open,
  onOpenChange,
}: PlayerScriptTooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [hasOpenedBefore, setHasOpenedBefore] = useState(false);

  // Sync with external open prop (triggered from mobile toolbar)
  useEffect(() => {
    if (open && !isOpen) {
      handleOpenScript();
    }
  }, [open]);

  // 从 localStorage 恢复状态
  useEffect(() => {
    if (sessionId) {
      const key = `script_opened_${sessionId}`;
      const opened = localStorage.getItem(key) === "true";
      setHasOpenedBefore(opened);
    }
  }, [sessionId]);

  // 保存状态到 localStorage
  const handleOpenScript = () => {
    setIsOpen(true);
    if (sessionId) {
      const key = `script_opened_${sessionId}`;
      localStorage.setItem(key, "true");
      setHasOpenedBefore(true);
    }
  };

  if (!scriptContent) return null;

  // 是否显示发光效果（新游戏且未打开过)
  const showGlow = !hasOpenedBefore && !isOpen;

  return (
    <>
      {/* Floating button - desktop only (hidden on mobile, toolbar provides button) */}
      <motion.button
        onClick={handleOpenScript}
        className={`fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full
                   bg-primary/90 hover:bg-primary text-foreground
                   shadow-lg hidden lg:flex flex-col items-center justify-center gap-1
                   transition-colors ${showGlow ? "breathing-prominent" : ""}`}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        title="查看我的剧本"
        style={
          showGlow
            ? {
                boxShadow:
                  "0 0 20px rgba(var(--primary-rgb, 59, 130, 246), 0.5), 0 0 40px rgba(var(--primary-rgb, 59, 130, 246), 0.3)",
              }
            : undefined
        }
      >
        <BookOpen className="w-6 h-6" />
        {showGlow && (
          <span className="absolute -top-1 -right-1 px-1.5 py-0.5 rounded-full bg-accent text-[10px] font-bold text-accent-foreground animate-pulse">
            新
          </span>
        )}
      </motion.button>

      {/* Modal */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => {
              setIsOpen(false);
              onOpenChange?.(false);
            }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="bg-card rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-border/50">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-bold">
                    {characterName ? `${characterName}的剧本` : "我的剧本"}
                  </h3>
                </div>
                <button
                  onClick={() => {
                    setIsOpen(false);
                    onOpenChange?.(false);
                  }}
                  className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Guidance tip */}
              <div className="px-4 pt-3">
                <div className="flex items-start gap-2 p-3 rounded-lg bg-primary/5 border border-primary/10">
                  <Lightbulb className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                  <p className="text-xs text-muted-foreground">
                    这是你的角色剧本，包含你的身份、背景和秘密。在发言时请保持角色一致性，不要暴露关键信息。如果是凶手，请自然地隐藏身份。
                  </p>
                </div>
              </div>

              {/* Content */}
              <div className="p-4 overflow-y-auto max-h-[calc(80vh-180px)] scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  {scriptContent.split("\n").map((paragraph, index) => {
                    // Skip empty lines
                    if (!paragraph.trim()) return null;

                    // Check if it's a heading-like line (starts with 【 or similar markers)
                    const isHeading = /^[【\[（(]/.test(paragraph.trim());

                    if (isHeading) {
                      return (
                        <h4
                          key={index}
                          className="text-base font-bold text-foreground mt-4 mb-2 first:mt-0"
                          dangerouslySetInnerHTML={{
                            __html: renderMarkdownText(paragraph),
                          }}
                        />
                      );
                    }

                    return (
                      <p
                        key={index}
                        className="mb-3 text-muted-foreground leading-relaxed"
                        dangerouslySetInnerHTML={{
                          __html: renderMarkdownText(paragraph),
                        }}
                      />
                    );
                  })}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
