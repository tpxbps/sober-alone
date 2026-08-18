import { useState, useRef, useEffect, useCallback } from "react";
import { Send, X, Loader2 } from "lucide-react";
import { AI_MODELS } from "@/types/game";
import type { ChatMessage } from "@/types/editor";
import { editorApi } from "@/lib/editorApi";
import { systemApi } from "@/lib/api";
import { configuredModels } from "@/lib/capabilityAdapter";
import { Markdown } from "@/components/ui/Markdown";

interface ChatPanelProps {
  threadId: string | null;
  onClose?: () => void;
}

function generateSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function ChatPanel({ threadId, onClose }: ChatPanelProps) {
  const [chatSessionId] = useState(() => generateSessionId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState(AI_MODELS[0].id);
  const [availableModels, setAvailableModels] = useState<typeof AI_MODELS>([]);
  const [modelReason, setModelReason] = useState("正在检查模型能力…");
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    systemApi
      .getCapabilities()
      .then((capabilities) => {
        const models = configuredModels(AI_MODELS, capabilities);
        setAvailableModels(models);
        setModelReason(models.length ? "" : "没有已配置的模型");
        if (models[0]) setModel(models[0].id);
      })
      .catch(() => {
        setAvailableModels([]);
        setModelReason("无法读取后端模型能力");
      });
  }, []);

  // Check if user is near bottom
  const isNearBottom = () => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  // Track user scroll behavior
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => {
      userScrolledUp.current = !isNearBottom();
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll only when user hasn't scrolled up
  useEffect(() => {
    if (scrollRef.current && !userScrolledUp.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming || availableModels.length === 0) return;

    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setIsStreaming(true);

    // Placeholder for assistant response
    const assistantMsg: ChatMessage = { role: "assistant", content: "" };
    setMessages([...newMessages, assistantMsg]);

    try {
      abortRef.current = new AbortController();

      await editorApi.streamChat(
        {
          message: trimmed,
          model,
          chat_session_id: chatSessionId,
          workflow_thread_id: threadId || undefined,
        },
        abortRef.current.signal,
        (token: string) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + token,
                thinkingTip: undefined, // Clear tip on first token
              };
            }
            return updated;
          });
        },
        () => {
          setIsStreaming(false);
        },
        (error: string) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || `[错误: ${error}]`,
              };
            }
            return updated;
          });
          setIsStreaming(false);
        },
        // onThinking callback
        (tip: string) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                thinkingTip: tip,
              };
            }
            return updated;
          });
        }
      );
    } catch {
      setIsStreaming(false);
    }
  }, [input, isStreaming, messages, model, chatSessionId, threadId, availableModels.length]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border/30 flex items-center justify-between">
        <span className="text-sm font-medium">创作小助手</span>
        <div className="flex items-center gap-2">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={availableModels.length === 0}
            title={modelReason}
            className="text-xs px-2 py-1 rounded border border-border/50 bg-card focus:outline-none focus:border-primary/50"
          >
            {availableModels.length === 0 && (
              <option value={model}>{modelReason}</option>
            )}
            {availableModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 hover:bg-secondary rounded transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin"
      >
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-s text-muted-foreground/50 text-center">
              有任何创作问题，随时问我 😊
            </p>
          </div>
        )}
        {messages.map((msg, i) => {
          const isLastAssistant =
            msg.role === "assistant" && i === messages.length - 1;
          const showThinking = isLastAssistant && isStreaming;

          return (
            <div
              key={i}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-[90%] rounded-lg ${
                  msg.role === "user"
                    ? "px-3 py-2 bg-primary text-primary-foreground text-sm"
                    : "px-1 py-0"
                }`}
              >
                {/* Thinking tip */}
                {msg.thinkingTip && showThinking && (
                  <div className="mb-1.5 px-2 py-1 rounded bg-primary/10 text-xs text-primary/80 flex items-center gap-1.5">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>{msg.thinkingTip}</span>
                  </div>
                )}

                {/* Generic thinking indicator */}
                {showThinking && !msg.content && !msg.thinkingTip && (
                  <div className="text-xs text-muted-foreground flex items-center gap-1.5 px-3 py-2">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>思考中</span>
                    <span className="animate-pulse">...</span>
                  </div>
                )}

                {/* Content */}
                {msg.role === "user" ? (
                  <span className="whitespace-pre-wrap">{msg.content}</span>
                ) : msg.content ? (
                  <div className="text-sm">
                    <Markdown>{msg.content}</Markdown>
                    {showThinking && (
                      <span className="inline-block w-1.5 h-3.5 bg-foreground/70 animate-pulse ml-0.5" />
                    )}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* Input */}
      <div className="shrink-0 p-3 border-t border-border/30">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息..."
            rows={3}
            className="flex-1 px-4 py-3 rounded-lg border border-border/50 bg-card text-sm leading-relaxed resize-none focus:outline-none focus:border-primary/50 transition-colors placeholder:text-muted-foreground/50 max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || availableModels.length === 0}
            className="shrink-0 p-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
