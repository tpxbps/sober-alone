import { useRef, useEffect, useState, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Info } from "lucide-react";
import type {
  GameRecord,
  Character,
  GameStage,
  AgentLlmInfo,
} from "@/types/game";
import { AI_MODELS } from "@/types/game";
import { Markdown } from "@/components/ui/Markdown";
import { GameMessageMarkdown } from "@/components/ui/GameMessageMarkdown";
import { StreamingBubble } from "@/components/game/StreamingBubble";
import { ChatInputArea } from "@/components/game/ChatInputArea";
import { SpeakerIcon, type SpeakerState } from "@/components/ui/SpeakerIcon";
import { AudioSpeedButton } from "@/components/ui/AudioSpeedButton";
import { audioPlayerManager } from "@/lib/audioPlayerManager";
import { useSettingsStore } from "@/stores/settingsStore";

const THINKING_MESSAGES = [
  "大家正在分析听到的发言",
  "这段发言引发了大家的深思",
  "众人正在消化这些信息",
];

function formatAudioTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

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
  onSendMessage,
  onAdvanceStage,
  onEndGame,
  canAdvanceEarly = false,
}: ChatAreaProps) {
  const [thinkingMessage, setThinkingMessage] = useState(THINKING_MESSAGES[0]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // TTS state tracking per-record: recordId -> 'loading' | 'playing' | 'error'
  const [ttsStates, setTtsStates] = useState<Record<number, SpeakerState>>({});
  const [ttsProgress, setTtsProgress] = useState<
    Record<number, { current: number; duration: number }>
  >({});
  const [sysAudioStates, setSysAudioStates] = useState<
    Record<number, SpeakerState>
  >({});
  const ttsEnabled = useSettingsStore((s) => s.ttsEnabled);

  // User scroll priority ref: shared with StreamingBubble via DOM event
  const userScrollTimerRef = useRef<number>(0);

  // Track active audio across all handlers: enables toggle-off and SSE abort
  const activeAudioRef = useRef<{
    recordId: number;
    type: "static" | "streaming";
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

  // Stop active audio when TTS is disabled mid-game
  useEffect(() => {
    if (!ttsEnabled) {
      stopActiveAudio();
    }
  }, [ttsEnabled, stopActiveAudio]);

  // Handle TTS playback for a record (AI speech — Blob cache, audio_url, or SSE stream)
  const handlePlayRecordAudio = useCallback(
    async (record: GameRecord) => {
      // If already playing this record → stop (toggle off)
      if (
        activeAudioRef.current?.recordId === record.id &&
        audioPlayerManager.isAudioActive()
      ) {
        stopActiveAudio();
        return;
      }

      // Stop whatever else is playing
      stopActiveAudio();

      // Check frontend Blob cache first
      const cachedUrl = audioPlayerManager.getCachedUrl(record.id);
      if (cachedUrl) {
        activeAudioRef.current = { recordId: record.id, type: "static" };
        setTtsStates({ [record.id]: "playing" });
        try {
          await audioPlayerManager.play(cachedUrl);
          const unsub = audioPlayerManager.onStateChange((playing) => {
            if (!playing && !audioPlayerManager.isAudioActive()) {
              setTtsStates((prev) => ({ ...prev, [record.id]: "off" }));
              if (activeAudioRef.current?.recordId === record.id)
                activeAudioRef.current = null;
              unsub();
            }
          });
        } catch {
          setTtsStates({ [record.id]: "error" });
          activeAudioRef.current = null;
        }
        return;
      }

      // Check backend pre-generated audio_url
      if (record.audio_url) {
        activeAudioRef.current = { recordId: record.id, type: "static" };
        setTtsStates({ [record.id]: "loading" });
        try {
          await audioPlayerManager.play(record.audio_url);
          setTtsStates({ [record.id]: "playing" });
          const unsub = audioPlayerManager.onStateChange((playing) => {
            if (!playing && !audioPlayerManager.isAudioActive()) {
              setTtsStates((prev) => ({ ...prev, [record.id]: "off" }));
              if (activeAudioRef.current?.recordId === record.id)
                activeAudioRef.current = null;
              unsub();
            }
          });
        } catch {
          setTtsStates({ [record.id]: "error" });
          activeAudioRef.current = null;
        }
        return;
      }

      // AI character record: stream TTS via SSE
      if (record.speaker_id && record.speaker_id !== humanCharacterId) {
        const abortController = new AbortController();
        activeAudioRef.current = {
          recordId: record.id,
          type: "streaming",
          abortController,
        };

        setTtsStates({ [record.id]: "loading" });

        try {
          await audioPlayerManager.startStream();
          setTtsStates({ [record.id]: "playing" });

          // Listen for streaming audio end to reset speaker state
          const unsub = audioPlayerManager.onStateChange((playing) => {
            if (!playing && !audioPlayerManager.isAudioActive()) {
              setTtsStates((prev) => ({ ...prev, [record.id]: "off" }));
              if (activeAudioRef.current?.recordId === record.id)
                activeAudioRef.current = null;
              unsub();
            }
          });

          const apiBase = import.meta.env.VITE_API_URL || "/api/v1";
          const response = await fetch(
            `${apiBase}/game/${record.session_id}/tts/stream`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ record_id: record.id }),
              signal: abortController.signal,
            }
          );

          if (!response.body) throw new Error("No response body");

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                const data = JSON.parse(line.slice(6));
                // Guard: ignore stale chunks if user switched to different audio
                if (activeAudioRef.current?.recordId !== record.id) return;
                if (data.type === "audio_delta" && data.audio) {
                  await audioPlayerManager.appendChunk(data.audio);
                } else if (data.type === "audio_done") {
                  audioPlayerManager.endStream(record.id);
                } else if (data.type === "error") {
                  audioPlayerManager.stop();
                  setTtsStates({ [record.id]: "error" });
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
          if ((e as Error).name !== "AbortError") {
            audioPlayerManager.stop();
            setTtsStates({ [record.id]: "error" });
          }
          activeAudioRef.current = null;
        }
      }
    },
    [humanCharacterId, stopActiveAudio]
  );

  // Handle system message audio playback
  const handlePlaySystemAudio = useCallback(
    async (record: GameRecord) => {
      // If already playing this system record → toggle pause/resume
      if (
        activeAudioRef.current?.recordId === record.id &&
        audioPlayerManager.isAudioActive()
      ) {
        const resumed = audioPlayerManager.togglePause();
        setSysAudioStates((prev) => ({
          ...prev,
          [record.id]: resumed ? "playing" : "off",
        }));
        return;
      }

      // Stop whatever else is playing
      stopActiveAudio();

      if (!record.audio_url) return;

      activeAudioRef.current = { recordId: record.id, type: "static" };
      setSysAudioStates({ [record.id]: "loading" });
      setTtsProgress({});
      try {
        await audioPlayerManager.play(record.audio_url);
        setSysAudioStates({ [record.id]: "playing" });
        const unsub = audioPlayerManager.onStateChange(
          (playing, currentTime, duration) => {
            if (!playing && !audioPlayerManager.isAudioActive()) {
              setSysAudioStates((prev) => ({ ...prev, [record.id]: "off" }));
              setTtsProgress((prev) => {
                const next = { ...prev };
                delete next[record.id];
                return next;
              });
              if (activeAudioRef.current?.recordId === record.id)
                activeAudioRef.current = null;
              unsub();
            } else if (playing) {
              setTtsProgress((prev) => ({
                ...prev,
                [record.id]: { current: currentTime, duration },
              }));
            }
          }
        );
      } catch {
        setSysAudioStates({ [record.id]: "error" });
        activeAudioRef.current = null;
      }
    },
    [stopActiveAudio]
  );

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

  // Check if human is current speaker
  const isHumanTurn = currentSpeakerId === humanCharacterId || hasHumanTurn;

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
                const sysSpeakerState: SpeakerState = record.audio_url
                  ? sysAudioStates[record.id] || "off"
                  : "disabled";
                const sysProg = ttsProgress[record.id];
                const isPlaying = sysSpeakerState === "playing";
                return (
                  <motion.div
                    key={record.id || index}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="flex justify-center"
                  >
                    <div
                      className="px-5 py-3 rounded-2xl bg-gradient-to-r from-primary/10 via-accent/5 to-primary/10
                                  border border-primary/20 max-w-[85%] shadow-sm"
                    >
                      {record.audio_url ? (
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Info className="w-3.5 h-3.5 text-primary shrink-0" />
                          <span className="text-xs text-primary/60 font-medium">
                            系统消息
                          </span>
                          <span className="text-[9px] text-muted-foreground/70">
                            AI 生成语音
                          </span>
                          <SpeakerIcon
                            state={sysSpeakerState}
                            onClick={() => handlePlaySystemAudio(record)}
                            size={16}
                            className="shrink-0 ml-1"
                          />
                          {isPlaying && sysProg && (
                            <>
                              <span className="text-[10px] text-muted-foreground tabular-nums">
                                {formatAudioTime(sysProg.current)}
                              </span>
                              <input
                                type="range"
                                min={0}
                                max={sysProg.duration || 0}
                                step={0.1}
                                value={sysProg.current}
                                onChange={(e) =>
                                  audioPlayerManager.seekTo(
                                    Number(e.target.value)
                                  )
                                }
                                className="w-[50%] h-0.5 rounded-full appearance-none bg-secondary cursor-pointer
                                           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2
                                           [&::-webkit-slider-thumb]:h-2 [&::-webkit-slider-thumb]:rounded-full
                                           [&::-webkit-slider-thumb]:bg-primary"
                              />
                              <span className="text-[10px] text-muted-foreground tabular-nums">
                                {formatAudioTime(sysProg.duration)}
                              </span>
                            </>
                          )}
                          {isPlaying && <AudioSpeedButton />}
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Info className="w-3.5 h-3.5 text-primary shrink-0" />
                          <span className="text-xs text-primary/60 font-medium">
                            系统消息
                          </span>
                        </div>
                      )}
                      <Markdown className="text-sm text-foreground/90 leading-relaxed">
                        {record.content}
                      </Markdown>
                    </div>
                  </motion.div>
                );
              }

              // Player message styling
              const isAI = !isHuman && record.speaker_id;
              const recordSpeakerState: SpeakerState = isAI
                ? ttsEnabled
                  ? ttsStates[record.id] || "off"
                  : "disabled"
                : "disabled";

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
                      {isAI && ttsEnabled && (
                        <span className="ml-1 text-[9px] text-muted-foreground/60">
                          AI 生成语音
                        </span>
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
      <ChatInputArea
        stage={stage}
        isStreaming={isStreaming}
        isProcessingReactions={isProcessingReactions}
        isAdvancingStage={isAdvancingStage}
        isHumanTurn={isHumanTurn}
        canAdvanceEarly={canAdvanceEarly}
        humanRemainingSpeechCount={humanRemainingSpeechCount}
        pendingHumanSpeech={pendingHumanSpeech}
        thinkingMessage={thinkingMessage}
        streamingSpeakerName={
          getCharacter(streamingSpeakerId || undefined)?.name || "AI"
        }
        currentSpeakerId={currentSpeakerId}
        currentSpeakerName={
          getCharacter(currentSpeakerId || undefined)?.name || "..."
        }
        onSendMessage={onSendMessage}
        onAdvanceStage={onAdvanceStage}
        onEndGame={onEndGame}
        onSetPendingHumanSpeech={setPendingHumanSpeech}
      />
    </div>
  );
}
