import { useGameStore } from "@/stores/gameStore";
import { useState, useEffect, useRef, useCallback, memo } from "react";
import { Send, Loader2, ArrowRight, Plus, X, CircleHelp } from "lucide-react";
import { speechClues } from "@/lib/clueScope";
import { Switch } from "@/components/ui/switch";
import { DynamicDot } from "@/components/ui/DynamicDot";
import type { Character, PublicClue } from "@/types/game";
import { GameMessageMarkdown } from "@/components/ui/GameMessageMarkdown";
import {
  MentionComposer,
  type MentionComposerHandle,
} from "./MentionComposer";

interface ChatInputAreaProps {
  stage: string;
  isStreaming: boolean;
  isProcessingReactions: boolean;
  isAdvancingStage: boolean;
  isHumanTurn: boolean;
  canAdvanceEarly: boolean;
  humanRemainingSpeechCount?: number;
  pendingHumanSpeech: string | null;
  thinkingMessage: string;
  streamingSpeakerName: string;
  currentSpeakerId: string | null;
  currentSpeakerName: string;
  onSendMessage: (content: string) => void;
  onAdvanceStage: () => void;
  onEndGame: () => void;
  onSetPendingHumanSpeech: (speech: string | null, clues?: PublicClue[]) => void;
  characters: Character[];
  publicClues: PublicClue[];
  mentionRequest?: { character: Character; nonce: number } | null;
  pauseAutoSpeak: boolean;
  onPauseAutoSpeakChange: (value: boolean) => void;
  onHumanSpeechCompleted: () => void;
}

export const ChatInputArea = memo(function ChatInputArea({
  stage,
  isStreaming,
  isProcessingReactions,
  isAdvancingStage,
  isHumanTurn,
  canAdvanceEarly,
  humanRemainingSpeechCount,
  pendingHumanSpeech,
  thinkingMessage,
  streamingSpeakerName,
  currentSpeakerId,
  currentSpeakerName,
  onSendMessage,
  onAdvanceStage,
  onEndGame,
  onSetPendingHumanSpeech,
  characters,
  publicClues,
  mentionRequest,
  pauseAutoSpeak,
  onPauseAutoSpeakChange,
  onHumanSpeechCompleted,
}: ChatInputAreaProps) {
  const recoveryRequired = useGameStore(state => state.speechGeneration?.status === 'failed' || !!state.speechConnectionError);
  const [input, setInput] = useState("");
  const [draftClues, setDraftClues] = useState<PublicClue[] | null>(null);
  const availableClues = draftClues ?? speechClues(stage, publicClues);
  const [pendingLines, setPendingLines] = useState<string[]>([]);
  const inputRef = useRef<MentionComposerHandle>(null);

  // Focus input when it's human's turn
  useEffect(() => {
    if (isHumanTurn && !isStreaming && stage !== "vote") {
      inputRef.current?.focus();
    }
  }, [isHumanTurn, isStreaming, stage]);

  useEffect(() => {
    if (mentionRequest) inputRef.current?.insertMention(mentionRequest.character);
  }, [mentionRequest]);

  const clearInput = () => {
    inputRef.current?.clear();
    setInput("");
  };

  // Handle message submit
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || !isHumanTurn) return;
    setPendingLines((prev) => [...prev, input.trim()]);
    clearInput();
  };

  // Handle end speech - submit all pending lines
  const handleEndSpeech = useCallback(() => {
    if (recoveryRequired) return;
    const allLines = [...pendingLines];
    if (input.trim()) {
      allLines.push(input.trim());
    }
    if (allLines.length === 0) return;

    const fullSpeech = allLines.join("\n");
    onHumanSpeechCompleted();

    // 自由发言阶段且AI正在发言：暂存发言，等待AI完成
    if (stage === "free_discussion" && (isStreaming || isProcessingReactions)) {
      onSetPendingHumanSpeech(fullSpeech, availableClues);
      setDraftClues(null);
      setPendingLines([]);
      clearInput();
      return;
    }

    // 其他阶段或AI未发言：直接发送
    onSendMessage(fullSpeech);
    setDraftClues(null);
    setPendingLines([]);
    clearInput();
  }, [
    recoveryRequired,
    input,
    pendingLines,
    stage,
    isStreaming,
    isProcessingReactions,
    onSendMessage,
    onSetPendingHumanSpeech,
    onHumanSpeechCompleted,
    availableClues,
  ]);

  const inputDisabled =
    !!pendingHumanSpeech ||
    (stage !== "free_discussion" && (isStreaming || isProcessingReactions)) ||
    (stage === "free_discussion" &&
      humanRemainingSpeechCount !== undefined &&
      humanRemainingSpeechCount <= 0);

  return (
    <div data-game-composer className="border-t border-border/50 p-4 bg-card/30">
      <div className="max-w-3xl mx-auto">
        {/* Stage is review - show results and end game button */}
        {stage === "review" ? (
          <div className="text-center space-y-4 py-4">
            <p className="text-muted-foreground">
              游戏已结束，点击按钮返回主页
            </p>
            <button
              onClick={onEndGame}
              disabled={isAdvancingStage || recoveryRequired}
              className="px-8 py-3 rounded-xl bg-primary text-primary-foreground font-medium
                       hover:bg-primary/90 transition-colors flex items-center gap-2 mx-auto
                       disabled:opacity-50 disabled:cursor-not-allowed"
            >
              结束游戏 · 返回主页
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        ) : stage === "vote" ? (
          <div className="text-center py-4">
            <p className="text-muted-foreground mb-4">
              剩余玩家正在进行投票，请稍候
              <DynamicDot />
            </p>
          </div>
        ) : isAdvancingStage ? (
          <div className="flex items-center justify-center gap-3 py-4 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>
              正在推进游戏
              <DynamicDot />
            </span>
          </div>
        ) : isProcessingReactions && stage !== "free_discussion" ? (
          <div className="flex items-center justify-center gap-3 py-4 text-muted-foreground">
            <span>
              {thinkingMessage}
              <DynamicDot />
            </span>
          </div>
        ) : stage === "free_discussion" || isHumanTurn ? (
          <form onSubmit={handleSubmit} className="space-y-3">
            {/* AI speaking status indicator */}
            {(isStreaming || isProcessingReactions) && (
              <div className="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>
                  {isStreaming
                    ? `${streamingSpeakerName || "AI"} 正在发言`
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
                    <GameMessageMarkdown characters={characters} publicClues={availableClues} allowedCitationIds={availableClues.map(clue => clue.id)} preserveWhitespace>
                      {line}
                    </GameMessageMarkdown>
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
            {/* Advance early button */}
            {canAdvanceEarly && !isStreaming && !isProcessingReactions && (
              <div className="flex justify-center pb-2">
                <button
                  type="button"
                  onClick={onAdvanceStage}
                  disabled={isAdvancingStage || recoveryRequired}
                  className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium
                           hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed
                           transition-colors flex items-center gap-2"
                >
                  进入下一阶段
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            )}
            <div className="flex gap-2 lg:gap-3">
              <div className="flex-1 relative flex">
                <MentionComposer
                  ref={inputRef}
                  toolbar={stage === "free_discussion" ? <div className="flex h-7 items-center gap-2 text-xs">
                    <label className="inline-flex cursor-pointer items-center gap-2 py-1">
                      <Switch compact aria-label="让我想想" aria-describedby="pause-speech-help"
                        checked={pauseAutoSpeak} onCheckedChange={onPauseAutoSpeakChange} />
                      <span className={pauseAutoSpeak ? 'text-primary' : 'text-muted-foreground'}>让我想想</span>
                    </label>
                    <span tabIndex={0} aria-label="暂停说明"
                      className="group relative outline-none">
                      <CircleHelp className="h-3.5 w-3.5 text-muted-foreground/60" />
                      <span id="pause-speech-help" role="tooltip" className="pointer-events-none absolute bottom-full left-0 z-50 mb-2 hidden w-52 rounded-lg border border-border bg-popover p-2 text-xs leading-relaxed shadow-lg group-hover:block group-focus:block">
                        开启后AI角色将暂时停止自主发言。
                      </span>
                    </span>
                    <span role="status" className="hidden text-[11px] text-primary/80 sm:inline">
                      {pauseAutoSpeak && !isStreaming && !isProcessingReactions && "AI 已暂停"}
                    </span>
                  </div> : undefined}
                  characters={characters}
                  clues={availableClues}
                  disabled={inputDisabled}
                  maxLength={3000}
                  onChange={value => {
                    setInput(value);
                    if (value) setDraftClues(previous => previous ?? speechClues(stage, publicClues));
                  }}
                  onCtrlEnter={handleEndSpeech}
                  onEnter={() => {
                    if (!input.trim()) return;
                    setPendingLines((prev) => [...prev, input.trim()]);
                    clearInput();
                  }}
                />
                <span
                  className={`absolute top-3 right-3 text-[10px] leading-none pointer-events-none select-none ${
                    input.length > 2700
                      ? "text-destructive"
                      : "text-muted-foreground/40"
                  }`}
                >
                  {input.length}/3000
                </span>
              </div>
              <div className="flex flex-col gap-1.5 lg:gap-2">
                <button
                  type="submit"
                  disabled={
                    recoveryRequired || !!pendingHumanSpeech ||
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
                  aria-label="完成发言"
                  onClick={handleEndSpeech}
                  disabled={
                    recoveryRequired || !!pendingHumanSpeech ||
                    (pendingLines.length === 0 && !input.trim()) ||
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
            <div className="flex flex-wrap items-center justify-between gap-1 text-[11px] text-muted-foreground/70">
              <span className="hidden lg:inline">Enter 添加内容 · Ctrl+Enter 完成发言</span>
              {stage === "free_discussion" && humanRemainingSpeechCount !== undefined && <span className="ml-auto">剩余发言次数: {humanRemainingSpeechCount}</span>}
            </div>
          </form>
        ) : /* Can advance stage — only when no current speaker and nothing processing */
        currentSpeakerId === null &&
          !isProcessingReactions &&
          !isStreaming &&
          !isAdvancingStage ? (
          <div className="flex justify-center">
            <button
              onClick={onAdvanceStage}
              disabled={isAdvancingStage || recoveryRequired}
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
            <span>{streamingSpeakerName} 正在发言</span>
            <DynamicDot />
          </div>
        ) : (
          <div className="flex items-center justify-center gap-3 py-3 text-muted-foreground">
            <span>等待 {currentSpeakerName} 发言</span>
          </div>
        )}
      </div>
    </div>
  );
});
