import { useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2 } from "lucide-react";
import { useGameStore } from "@/stores/gameStore";
import { AI_MODELS } from "@/types/game";
import { DynamicDot } from "@/components/ui/DynamicDot";

/**
 * StreamingBubble - 隔离渲染的流式消息气泡
 *
 * 直接从 zustand store 订阅流式状态（streamingContent, isStreaming 等），
 * 这样 streamingContent 的每次更新只会重渲染这一个组件，
 * 不会导致 ChatArea 及其子组件（records 列表、输入框等）重渲染。
 */
export function StreamingBubble() {
  // 使用 selector 精确订阅需要的字段
  const isStreaming = useGameStore((s) => s.isStreaming);
  const streamingContent = useGameStore((s) => s.streamingContent);
  const streamingSpeakerId = useGameStore((s) => s.streamingSpeakerId);
  const thinkingTip = useGameStore((s) => s.thinkingTip);
  const isProcessingReactions = useGameStore((s) => s.isProcessingReactions);
  const characters = useGameStore((s) => s.characters);
  const agentLlmInfo = useGameStore((s) => s.agentLlmInfo);

  // RAF-throttled scroll: only scroll once per animation frame at most
  const scrollRafRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // User scroll priority: tracks when user last scrolled up; auto-scroll pauses for 10s
  const userScrollTimerRef = useRef<number>(0);

  // Determine if the scroll container is at (or very near) the bottom
  const isAtBottom = useCallback(() => {
    const scrollParent = containerRef.current?.closest(".overflow-auto") as HTMLElement | null;
    if (!scrollParent) return true;
    const threshold = 80; // pixels from bottom to count as "at bottom"
    return scrollParent.scrollHeight - scrollParent.scrollTop - scrollParent.clientHeight < threshold;
  }, []);

  const scrollToBottom = useCallback(() => {
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      // Respect user scroll priority during streaming
      if (Date.now() < userScrollTimerRef.current) {
        scrollRafRef.current = null;
        return;
      }
      // Scroll the parent messages container
      const scrollParent = containerRef.current?.closest(".overflow-auto");
      if (scrollParent) {
        scrollParent.scrollTop = scrollParent.scrollHeight;
      }
      scrollRafRef.current = null;
    });
  }, []);

  // Auto-scroll when content changes
  useEffect(() => {
    if (streamingContent) {
      scrollToBottom();
    }
    return () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [streamingContent, scrollToBottom]);

  // Listen for scroll events on the scroll container to detect user scrolling up
  // Re-attach when isStreaming changes so the listener is bound after DOM renders
  useEffect(() => {
    const scrollParent = containerRef.current?.closest(".overflow-auto");
    if (!scrollParent) return;

    const handleScroll = () => {
      if (isAtBottom()) {
        // User scrolled to the bottom: clear the timer so auto-scroll resumes
        userScrollTimerRef.current = 0;
      } else {
        // User scrolled up (not at bottom): set 10-second timer
        userScrollTimerRef.current = Date.now() + 10000;
      }
    };

    scrollParent.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      scrollParent.removeEventListener("scroll", handleScroll);
    };
  }, [isAtBottom, isStreaming]);

  const shouldShow =
    (isStreaming || (isProcessingReactions && streamingContent)) &&
    streamingSpeakerId;

  if (!shouldShow) return null;

  const character = characters.find(
    (c) => c.character_id === streamingSpeakerId
  );

  const getModelDisplayName = (model: string | undefined | null) => {
    if (!model) return "";
    const found = AI_MODELS.find((m) => m.id === model);
    return found ? found.name : model;
  };

  return (
    <motion.div
      ref={containerRef}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3"
    >
      <div className="shrink-0 relative">
        <div
          className={`w-10 h-10 rounded-full overflow-hidden bg-gradient-to-br from-primary/30 to-accent/30
                      flex items-center justify-center text-sm font-bold ${
                        isStreaming ? "breathing" : ""
                      }`}
        >
          {character?.avatar_url ? (
            <img
              src={character.avatar_url}
              alt={character.name}
              className="w-full h-full object-cover"
            />
          ) : (
            <span>{character?.name?.[0] || "?"}</span>
          )}
        </div>
      </div>
      <div className="flex flex-col items-start max-w-[70%]">
        <span className="text-xs text-muted-foreground mb-1">
          {character?.name}
          {agentLlmInfo[streamingSpeakerId || ""] && (
            <span className="ml-1 text-muted-foreground/70">
              ({getModelDisplayName(agentLlmInfo[streamingSpeakerId || ""]?.model)})
            </span>
          )}
        </span>
        <div className="px-4 py-3 rounded-2xl bg-card border border-border/50 rounded-tl-sm">
          {/* Tool calling tip */}
          <AnimatePresence>
            {thinkingTip && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="mb-2 px-2 py-1 rounded bg-primary/10 text-xs text-primary/80
                         flex items-center gap-1.5 overflow-hidden"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>{thinkingTip}</span>
              </motion.div>
            )}
          </AnimatePresence>
          {/* Thinking UI */}
          <AnimatePresence>
            {isStreaming && !streamingContent.trim() && !thinkingTip && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-xs text-muted-foreground flex items-center gap-1.5"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>思考中</span>
                <DynamicDot />
              </motion.div>
            )}
          </AnimatePresence>
          {/* Streaming content - plain text, no markdown parsing */}
          {streamingContent.trim() && (
            <p className="text-sm whitespace-pre-wrap">
              {streamingContent}
              {isStreaming && (
                <span className="inline-block w-2 h-4 bg-primary ml-1 animate-pulse" />
              )}
            </p>
          )}
        </div>
      </div>
    </motion.div>
  );
}
