import { useRef, useEffect, useState, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Loader2, ArrowRight, Plus, Info, X } from "lucide-react";
import type {
  GameRecord,
  Character,
  GameStage,
  AgentLlmInfo,
} from "@/types/game";
import { AI_MODELS } from "@/types/game";
import { DynamicDot } from "@/components/ui/DynamicDot";
import { Markdown } from "@/components/ui/Markdown";
import { GameMessageMarkdown } from "@/components/ui/GameMessageMarkdown";
import { StreamingBubble } from "@/components/game/StreamingBubble";
import { SpeakerIcon, type SpeakerState } from "@/components/ui/SpeakerIcon";
import { audioPlayerManager } from "@/lib/audioPlayerManager";
import { useSettingsStore } from "@/stores/settingsStore";

const THINKING_MESSAGES = [
  "大家正在分析听到的发言",
  "这段发言引发了大家的深思",
  "众人正在消化这些信息",
];

interface ChatAreaProps {
  records: GameRecord[];
  characters: Character[];
  humanCharacterId: string | null;
  currentSpeakerId: string | null;
  stage: GameStage;
  isStreaming: boolean;
  streamingSpeakerId: string | null;
  hasHumanTurn: boolean;
  isProcessingReactions?: boolean; // 正在处理反应
  isAdvancingStage?: boolean; // 正在推进阶段
  agentLlmInfo?: Record<string, AgentLlmInfo>; // AI角色的LLM配置信息
  humanRemainingSpeechCount?: number; // 玩家剩余发言次数
  pendingHumanSpeech: string | null; // 待发送的真人发言
  setPendingHumanSpeech: (speech: string | null) => void; // 设置待发送发言
  scriptId?: string; // 剧本 ID，用于构建音频 URL
  onSendMessage: (content: string) => void;
  onAdvanceStage: () => void;
  onEndGame: () => void;
  /** 自由发言阶段，所有玩家是否都已发言至少一次（可提前推进） */
  canAdvanceEarly?: boolean;
}

// 格式化模型名称显示
function getModelDisplayName(modelId: string | undefined | null): string {
  if (!modelId) return "";
  const found = AI_MODELS.find((m) => m.id === modelId);
  return found ? found.name : modelId;
}

export function ChatArea({
  records,
  characters,
  humanCharacterId,
  currentSpeakerId,
  stage,
  isStreaming,
  streamingSpeakerId,
  hasHumanTurn,
  isProcessingReactions = false,
  isAdvancingStage = false,
  agentLlmInfo = {},
  humanRemainingSpeechCount,
  pendingHumanSpeech,
  setPendingHumanSpeech,
  scriptId,
  onSendMessage,
  onAdvanceStage,
  onEndGame,
  canAdvanceEarly = false,
}: ChatAreaProps) {
  const [input, setInput] = useState("");
  const [pendingLines, setPendingLines] = useState<string[]>([]);
  const [thinkingMessage, setThinkingMessage] = useState(THINKING_MESSAGES[0]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // TTS state tracking per-record: recordId -> 'loading' | 'playing' | 'error'
  const [ttsStates, setTtsStates] = useState<Record<number, SpeakerState>>({});
  const ttsEnabled = useSettingsStore((s) => s.ttsEnabled);

  // User scroll priority ref: shared with StreamingBubble via DOM event
  const userScrollTimerRef = useRef<number>(0);

  // Track active audio across all handlers: enables toggle-off and SSE abort
  const activeAudioRef = useRef<{
    recordId: number;
    type: 'static' | 'streaming';
    abortController?: AbortController;
  } | null>(null);

  /** Stop current active audio (abort SSE if streaming) */
  const stopActiveAudio = useCallback(() => {
    if (activeAudioRef.current) {
      activeAudioRef.current.abortController?.abort();
      activeAudioRef.current = null;
    }
    if (audioPlayerManager.getIsPlaying()) {
      audioPlayerManager.stop();
    }
    setTtsStates({});
  }, []);

  // Handle TTS playback for a record (AI speech — Blob cache, audio_url, or SSE stream)
  const handlePlayRecordAudio = useCallback(async (record: GameRecord) => {
    // If already playing this record → stop (toggle off)
    if (activeAudioRef.current?.recordId === record.id && audioPlayerManager.isAudioActive()) {
      stopActiveAudio();
      return;
    }

    // Stop whatever else is playing
    stopActiveAudio();

    // Check frontend Blob cache first
    const cachedUrl = audioPlayerManager.getCachedUrl(record.id);
    if (cachedUrl) {
      activeAudioRef.current = { recordId: record.id, type: 'static' };
      setTtsStates({ [record.id]: 'playing' });
      try {
        await audioPlayerManager.play(cachedUrl);
        const unsub = audioPlayerManager.onStateChange((playing) => {
          if (!playing && !audioPlayerManager.isAudioActive()) {
            setTtsStates(prev => ({ ...prev, [record.id]: 'off' }));
            if (activeAudioRef.current?.recordId === record.id) activeAudioRef.current = null;
            unsub();
          }
        });
      } catch {
        setTtsStates({ [record.id]: 'error' });
        activeAudioRef.current = null;
      }
      return;
    }

    // Check backend pre-generated audio_url
    if (record.audio_url) {
      activeAudioRef.current = { recordId: record.id, type: 'static' };
      setTtsStates({ [record.id]: 'loading' });
      try {
        await audioPlayerManager.play(record.audio_url);
        setTtsStates({ [record.id]: 'playing' });
        const unsub = audioPlayerManager.onStateChange((playing) => {
          if (!playing && !audioPlayerManager.isAudioActive()) {
            setTtsStates(prev => ({ ...prev, [record.id]: 'off' }));
            if (activeAudioRef.current?.recordId === record.id) activeAudioRef.current = null;
            unsub();
          }
        });
      } catch {
        setTtsStates({ [record.id]: 'error' });
        activeAudioRef.current = null;
      }
      return;
    }

    // AI character record: stream TTS via SSE
    if (record.speaker_id && record.speaker_id !== humanCharacterId) {
      const abortController = new AbortController();
      activeAudioRef.current = {
        recordId: record.id,
        type: 'streaming',
        abortController,
      };

      setTtsStates({ [record.id]: 'loading' });

      try {
        await audioPlayerManager.startStream();
        setTtsStates({ [record.id]: 'playing' });

        // Listen for streaming audio end to reset speaker state
        const unsub = audioPlayerManager.onStateChange((playing) => {
          if (!playing && !audioPlayerManager.isAudioActive()) {
            setTtsStates(prev => ({ ...prev, [record.id]: 'off' }));
            if (activeAudioRef.current?.recordId === record.id) activeAudioRef.current = null;
            unsub();
          }
        });

        const apiBase = import.meta.env.VITE_API_URL || '/api/v1';
        const response = await fetch(
          `${apiBase}/game/${record.session_id}/tts/stream`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ record_id: record.id }),
            signal: abortController.signal,
          }
        );

        if (!response.body) throw new Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const data = JSON.parse(line.slice(6));
              // Guard: ignore stale chunks if user switched to different audio
              if (activeAudioRef.current?.recordId !== record.id) return;
              if (data.type === 'audio_delta' && data.audio) {
                await audioPlayerManager.appendChunk(data.audio);
              } else if (data.type === 'audio_done') {
                audioPlayerManager.endStream(record.id);
              } else if (data.type === 'error') {
                audioPlayerManager.stop();
                setTtsStates({ [record.id]: 'error' });
                activeAudioRef.current = null;
                return;
              }
            } catch {
              // skip invalid JSON
            }
          }
        }
        // Streaming completed naturally
        if (activeAudioRef.current?.recordId === record.id) {
          activeAudioRef.current = null;
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          audioPlayerManager.stop();
          setTtsStates({ [record.id]: 'error' });
        }
        activeAudioRef.current = null;
      }
    }
  }, [humanCharacterId, stopActiveAudio]);

  // Handle system message audio playback
  const handlePlaySystemAudio = useCallback(async (record: GameRecord) => {
    // If already playing this system record → stop (toggle off)
    if (activeAudioRef.current?.recordId === record.id && audioPlayerManager.isAudioActive()) {
      stopActiveAudio();
      return;
    }

    // Stop whatever else is playing
    stopActiveAudio();

    if (!record.audio_url) return;

    activeAudioRef.current = { recordId: record.id, type: 'static' };
    setTtsStates({ [record.id]: 'loading' });
    try {
      await audioPlayerManager.play(record.audio_url);
      setTtsStates({ [record.id]: 'playing' });
      const unsub = audioPlayerManager.onStateChange((playing) => {
        if (!playing && !audioPlayerManager.isAudioActive()) {
          setTtsStates(prev => ({ ...prev, [record.id]: 'off' }));
          if (activeAudioRef.current?.recordId === record.id) activeAudioRef.current = null;
          unsub();
        }
      });
    } catch {
      setTtsStates({ [record.id]: 'error' });
      activeAudioRef.current = null;
    }
  }, [stopActiveAudio]);

  // Update thinking message when processing starts
  useEffect(() => {
    if (isProcessingReactions) {
      setThinkingMessage(
        THINKING_MESSAGES[Math.floor(Math.random() * THINKING_MESSAGES.length)]
      );
    }
  }, [isProcessingReactions]);

  // Get character info by ID
  const getCharacter = (characterId?: string): Character | undefined => {
    if (!characterId) return undefined;
    return characters.find((c) => c.character_id === characterId);
  };

  // Build character name list for highlighting
  const characterNamesArray = useMemo(() => {
    return characters.map((c) => c.name).filter(Boolean);
  }, [characters]);

  // Auto-scroll to bottom when records change (new complete message arrives).
  // Always scroll to bottom for new messages; streaming tokens are handled by StreamingBubble.
  // We also listen for scroll events to set the user scroll timer, which StreamingBubble reads.
  const scrollRafRef = useRef<number | null>(null);
  const prevRecordCountRef = useRef<number>(records.length);

  useEffect(() => {
    const newCount = records.length;

    // Only scroll when record count actually increases (new messages arrived).
    // Skip scroll when records are just replaced (same count, e.g. optimistic → server).
    if (newCount > prevRecordCountRef.current) {
      prevRecordCountRef.current = newCount;
      if (scrollRafRef.current !== null) return;
      scrollRafRef.current = requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
        userScrollTimerRef.current = 0;
        scrollRafRef.current = null;
      });
    } else {
      prevRecordCountRef.current = newCount;
    }

    return () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [records]);

  // Focus input when it's human's turn
  useEffect(() => {
    if (hasHumanTurn && !isStreaming && stage !== "vote") {
      inputRef.current?.focus();
    }
  }, [hasHumanTurn, isStreaming, stage]);

  // Handle message submit
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || !hasHumanTurn) return;
    // Add line to pending lines
    setPendingLines((prev) => [...prev, input.trim()]);
    setInput("");
  };

  // Handle end speech - submit all pending lines
  const handleEndSpeech = () => {
    const allLines = [...pendingLines];
    if (input.trim()) {
      allLines.push(input.trim());
    }
    if (allLines.length === 0) return;

    const fullSpeech = allLines.join("\n");

    // 自由发言阶段且AI正在发言：暂存发言，等待AI完成
    if (stage === "free_discussion" && (isStreaming || isProcessingReactions)) {
      setPendingHumanSpeech(fullSpeech);
      setPendingLines([]);
      setInput("");
      return;
    }

    // 其他阶段或AI未发言：直接发送
    onSendMessage(fullSpeech);
    setPendingLines([]);
    setInput("");
  };

  // Handle key press - Enter to add line, Ctrl+Enter to send all
  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && e.ctrlKey) {
      // Ctrl+Enter: send all and complete speech
      e.preventDefault();
      if (input.trim() || pendingLines.length > 0) {
        handleEndSpeech();
      }
    } else if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey) {
      // Enter: add line to pending
      e.preventDefault();
      if (input.trim()) {
        setPendingLines((prev) => [...prev, input.trim()]);
        setInput("");
      }
    }
    // Shift+Enter: 默认textarea行为，插入换行符
  };

  // Check if human is current speaker
  const isHumanTurn = currentSpeakerId === humanCharacterId || hasHumanTurn;

  // Check if stage is complete (no current speaker and not processing)
  const isStageComplete =
    currentSpeakerId === null &&
    !isProcessingReactions &&
    !isStreaming &&
    !isAdvancingStage;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Messages Area */}
      <div className="flex-1 overflow-auto p-4 scrollbar-thin">
        <div className="max-w-3xl mx-auto space-y-4">
          <AnimatePresence mode="popLayout">
            {records.map((record, index) => {
              const character = getCharacter(record.speaker_id);
              const isHuman = record.speaker_id === humanCharacterId;
              const isSystem = record.record_type === "system";

              // System message styling
              if (isSystem) {
                const sysSpeakerState: SpeakerState = ttsStates[record.id] || 'off';
                return (
                  <motion.div
                    key={record.id || index}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="flex justify-center"
                  >
                    <div
                      className="flex items-start gap-3 px-5 py-4 rounded-2xl bg-gradient-to-r from-primary/10 via-accent/5 to-primary/10
                                  border border-primary/20 max-w-[85%] shadow-sm"
                    >
                      <SpeakerIcon
                        state={sysSpeakerState}
                        onClick={() => handlePlaySystemAudio(record)}
                        size={14}
                        className="shrink-0 mt-0.5"
                      />
                      <Info className="w-5 h-5 text-primary shrink-0 mt-0.5" />
                      <Markdown className="text-sm text-foreground/90 leading-relaxed">
                        {record.content}
                      </Markdown>
                    </div>
                  </motion.div>
                );
              }

              // Player message styling
              const isAI = !isHuman && record.speaker_id;
              const recordSpeakerState: SpeakerState = isAI ? (ttsStates[record.id] || 'off') : 'disabled';

              return (
                <motion.div
                  key={record.id || index}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className={`flex gap-3 ${
                    isHuman ? "flex-row-reverse" : "flex-row"
                  }`}
                >
                  {/* Avatar with optional speaker icon */}
                  <div className="shrink-0 relative">
                    <div
                      className="w-10 h-10 rounded-full overflow-hidden bg-gradient-to-br from-primary/30 to-accent/30
                                  flex items-center justify-center text-sm font-bold"
                    >
                      {character?.avatar_url ? (
                        <img
                          src={character.avatar_url}
                          alt={character.name}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <span>{record.speaker_name?.[0] || "?"}</span>
                      )}
                    </div>
                    {/* Speaker icon for AI characters - positioned at top-right of avatar */}
                    {isAI && (
                      <div className="absolute -top-1.5 -right-1.5">
                        <SpeakerIcon
                          state={recordSpeakerState}
                          onClick={() => handlePlayRecordAudio(record)}
                          size={10}
                        />
                      </div>
                    )}
                  </div>

                  {/* Message */}
                  <div
                    className={`flex flex-col ${
                      isHuman ? "items-end" : "items-start"
                    } max-w-[70%]`}
                  >
                    <span
                      className={`text-xs text-muted-foreground mb-1 ${
                        isHuman ? "text-right" : "text-left"
                      }`}
                    >
                      {record.speaker_name}
                      {isHuman ? (
                        <span className="ml-1 text-accent">(你)</span>
                      ) : (
                        agentLlmInfo[record.speaker_id || ""] && (
                          <span className="ml-1 text-muted-foreground/70">
                            (
                            {getModelDisplayName(
                              agentLlmInfo[record.speaker_id || ""]?.model
                            )}
                            )
                          </span>
                        )
                      )}
                    </span>
                    <div
                      className={`px-4 py-3 rounded-2xl ${
                        isHuman
                          ? "bg-primary/20 border border-primary/30 rounded-tr-sm"
                          : "bg-card border border-border/50 rounded-tl-sm"
                      }`}
                    >
                      <GameMessageMarkdown
                        className="text-sm"
                        characterNames={characterNamesArray}
                        preserveWhitespace={isHuman}
                      >
                        {record.content}
                      </GameMessageMarkdown>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {/* Streaming message - isolated component subscribes to store directly */}
          <StreamingBubble />

          {/* Pending human message - shown when queued during AI speech */}
          {pendingHumanSpeech && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3 flex-row-reverse"
            >
              <div className="shrink-0">
                <div
                  className="w-10 h-10 rounded-full overflow-hidden bg-gradient-to-br from-primary/30 to-accent/30
                              flex items-center justify-center text-sm font-bold"
                >
                  {getCharacter(humanCharacterId || undefined)?.avatar_url ? (
                    <img
                      src={
                        getCharacter(humanCharacterId || undefined)?.avatar_url
                      }
                      alt={getCharacter(humanCharacterId || undefined)?.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span>
                      {getCharacter(humanCharacterId || undefined)?.name?.[0] ||
                        "你"}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex flex-col items-end max-w-[70%]">
                <span className="text-xs text-muted-foreground mb-1 text-right">
                  {getCharacter(humanCharacterId || undefined)?.name}
                  <span className="ml-1 text-accent">(你)</span>
                  <span className="ml-1 text-primary/70">(等待发送)</span>
                </span>
                <div className="px-4 py-3 rounded-2xl bg-primary/10 border border-primary/20 rounded-tr-sm opacity-70">
                  <p className="text-sm whitespace-pre-wrap">
                    {pendingHumanSpeech}
                  </p>
                </div>
              </div>
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="border-t border-border/50 p-4 bg-card/30">
        <div className="max-w-3xl mx-auto">
          {/* Stage is review - show results and end game button */}
          {stage === "review" ? (
            <div className="text-center space-y-4 py-4">
              <p className="text-muted-foreground">
                游戏已结束，点击按钮返回主页
              </p>
              <button
                onClick={onEndGame}
                disabled={isAdvancingStage}
                className="px-8 py-3 rounded-xl bg-primary text-primary-foreground font-medium
                         hover:bg-primary/90 transition-colors flex items-center gap-2 mx-auto
                         disabled:opacity-50 disabled:cursor-not-allowed"
              >
                结束游戏 · 返回主页
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          ) : /* Stage is vote - show voting UI instead */
          stage === "vote" ? (
            <div className="text-center py-4">
              <p className="text-muted-foreground mb-4">
                剩余玩家正在进行投票，请稍候
                <DynamicDot />
              </p>
            </div>
          ) : /* Advancing stage - show loading */
          isAdvancingStage ? (
            <div className="flex items-center justify-center gap-3 py-4 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span>
                正在推进游戏
                <DynamicDot />
              </span>
            </div>
          ) : /* Processing reactions in NON-free-discussion stages */
          isProcessingReactions && stage !== "free_discussion" ? (
            <div className="flex items-center justify-center gap-3 py-4 text-muted-foreground">
              <span>
                {thinkingMessage}
                <DynamicDot />
              </span>
            </div>
          ) : /* Free discussion stage OR human's turn - always show input */
          stage === "free_discussion" || isHumanTurn ? (
            <form onSubmit={handleSubmit} className="space-y-3">
              {/* AI speaking status indicator - shown above input */}
              {(isStreaming || isProcessingReactions) && (
                <div className="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>
                    {isStreaming
                      ? `${
                          getCharacter(streamingSpeakerId || undefined)?.name ||
                          "AI"
                        } 正在发言`
                      : thinkingMessage}
                  </span>
                  <DynamicDot />
                </div>
              )}
              {/* Pending human speech indicator */}
              {pendingHumanSpeech && (
                <div className="flex items-center justify-center gap-2 py-2 text-sm text-primary">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>你的发言将在AI发言结束后发送</span>
                  <DynamicDot />
                </div>
              )}
              {/* Pending lines preview */}
              {pendingLines.length > 0 && (
                <div className="flex flex-wrap gap-2 p-2 rounded bg-secondary/20 border border-border/30">
                  {pendingLines.map((line, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-primary/20 text-sm text-primary group"
                    >
                      {line}
                      <button
                        type="button"
                        onClick={() =>
                          setPendingLines((prev) =>
                            prev.filter((_, i) => i !== index)
                          )
                        }
                        className="opacity-50 hover:opacity-100 transition-opacity"
                        title="删除此条"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {/* 提前推进按钮：自由发言阶段所有玩家都发言过至少一次 */}
              {canAdvanceEarly && !isStreaming && !isProcessingReactions && (
                <div className="flex justify-center pb-2">
                  <button
                    type="button"
                    onClick={onAdvanceStage}
                    disabled={isAdvancingStage}
                    className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium
                             hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-colors flex items-center gap-2"
                  >
                    直接进入下一阶段
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              )}
              <div className="flex gap-2 lg:gap-3">
                <textarea
                  ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  placeholder="输入你的发言..."
                  maxLength={3000}
                  disabled={
                    !!pendingHumanSpeech ||
                    (stage !== "free_discussion" &&
                      (isStreaming || isProcessingReactions)) ||
                    (stage === "free_discussion" &&
                      humanRemainingSpeechCount !== undefined &&
                      humanRemainingSpeechCount <= 0)
                  }
                  rows={1}
                  className="flex-1 px-3 py-2 lg:px-4 lg:py-3 rounded-xl bg-secondary/30 border border-border/50
                           focus:outline-none focus:ring-2 focus:ring-primary/50
                           disabled:opacity-50 disabled:cursor-not-allowed resize-none text-sm"
                />
                <div className="flex flex-col gap-1.5 lg:gap-2">
                  <button
                    type="submit"
                    disabled={
                      !!pendingHumanSpeech ||
                      !input.trim() ||
                      isStreaming ||
                      isProcessingReactions
                    }
                    className="px-3 py-1.5 lg:px-4 lg:py-2 rounded-xl bg-secondary/50 border border-border/50 text-sm
                             hover:bg-secondary/70 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-colors flex items-center gap-1 whitespace-nowrap"
                    title="添加更多发言 (Enter)"
                  >
                    <Plus className="w-4 h-4" />
                    <span className="hidden sm:inline">继续发言</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleEndSpeech}
                    disabled={
                      !!pendingHumanSpeech ||
                      (pendingLines.length === 0 && !input.trim()) ||
                      (stage === "free_discussion" &&
                        (isStreaming || isProcessingReactions)) ||
                      (stage === "free_discussion" &&
                        humanRemainingSpeechCount !== undefined &&
                        humanRemainingSpeechCount <= 0)
                    }
                    className="px-3 py-1.5 lg:px-4 lg:py-2 rounded-xl bg-primary text-primary-foreground font-medium
                             hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-colors flex items-center gap-1 whitespace-nowrap"
                  >
                    <Send className="w-4 h-4" />
                    <span className="hidden sm:inline">完成发言</span>
                  </button>
                </div>
              </div>
              {/* Speech count indicator - hide keyboard shortcut hints on mobile */}
              {stage === "free_discussion" &&
                humanRemainingSpeechCount !== undefined && (
                  <p className="text-xs text-muted-foreground text-center">
                    剩余发言次数: {humanRemainingSpeechCount}
                    <span className="hidden lg:inline">
                      {" "}· Enter 添加更多内容 · Ctrl+Enter
                      发送全部发言并完成
                    </span>
                  </p>
                )}
              {stage !== "free_discussion" && (
                <p className="text-xs text-muted-foreground text-center hidden lg:block">
                  Enter 添加更多内容 · Ctrl+Enter 发送全部发言并完成
                </p>
              )}
            </form>
          ) : /* Can advance stage */
          isStageComplete ? (
            <div className="flex justify-center">
              <button
                onClick={onAdvanceStage}
                disabled={isAdvancingStage}
                className="px-8 py-4 rounded-xl bg-primary text-primary-foreground font-medium
                         hover:bg-primary/90 transition-colors flex items-center gap-2 glow
                         disabled:opacity-50 disabled:cursor-not-allowed"
              >
                进入下一阶段
                <ArrowRight className="w-5 h-5" />
              </button>
            </div>
          ) : /* AI streaming in non-free-discussion stages */
          isStreaming ? (
            <div className="flex items-center justify-center gap-2 py-3 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>
                {getCharacter(streamingSpeakerId || undefined)?.name || "AI"}{" "}
                正在发言
              </span>
              <DynamicDot />
            </div>
          ) : (
            <div className="flex items-center justify-center gap-3 py-3 text-muted-foreground">
              <span>
                等待{" "}
                {getCharacter(currentSpeakerId || undefined)?.name || "..."}{" "}
                发言
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
