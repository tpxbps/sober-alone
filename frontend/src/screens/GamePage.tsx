import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";

import { useGameStore } from "@/stores/gameStore";
import { GameHeader } from "@/components/game/GameHeader";
import { CharacterPanel } from "@/components/game/CharacterPanel";
import { ChatArea } from "@/components/game/ChatArea";
import { VotingModal } from "@/components/game/VotingModal";
import { StageTransitionOverlay } from "@/components/game/StageTransitionOverlay";
import { PlayerScriptTooltip } from "@/components/game/PlayerScriptTooltip";
import { DraftNotebook } from "@/components/game/DraftNotebook";
import { SettingsModal } from "@/components/SettingsModal";
import { useBGM } from "@/hooks/useBGM";
import type { GameStage, GameRecord } from "@/types/game";

interface GamePageProps {
  sessionId: string;
  onExit: () => void;
}

export function GamePage({ sessionId, onExit }: GamePageProps) {
  const [showVotingModal, setShowVotingModal] = useState(false);
  const [showScriptModal, setShowScriptModal] = useState(false);
  const [showCompletionModal, setShowCompletionModal] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showSpeechReminder, setShowSpeechReminder] = useState(false);
  const [speechReminderShown, setSpeechReminderShown] = useState(false);
  const [previousStage, setPreviousStage] = useState<GameStage | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { playStage } = useBGM();

  const {
    // State
    stage,
    currentRound,
    script,
    characters,
    playerStates,
    records,
    currentSpeakerId,
    humanCharacterId,
    humanCharacterScript,
    isStreaming,
    isProcessingReactions,
    isAdvancingStage,
    streamingSpeakerId,
    showStageTransition,
    stageTransitionMessage,
    voteResults,
    votes,
    agentLlmInfo,
    pendingHumanSpeech,

    // Actions
    initializeGame,
    advanceStage,
    humanSpeak,
    triggerAISpeak,
    submitVote,
    finalizeVoting,
    endGame,
    setStageTransition,
    addRecord,
    setPendingHumanSpeech,
    cancelActiveOperations,
  } = useGameStore();

  // Initialize game
  useEffect(() => {
    if (sessionId) {
      initializeGame(sessionId);
    }

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
      // Cancel all in-flight SSE streams when GamePage unmounts
      cancelActiveOperations();
    };
  }, [sessionId, initializeGame, cancelActiveOperations]);

  // Switch BGM based on game stage
  useEffect(() => {
    if (stage && stage !== "loading") {
      playStage(stage);
    }
  }, [stage, playStage]);

  // Show voting modal when entering vote stage
  useEffect(() => {
    if (stage === "vote" && !voteResults) {
      setShowVotingModal(true);
    } else {
      setShowVotingModal(false);
    }
  }, [stage, voteResults]);

  // Show completion modal when game ends + auto-redirect countdown
  const [completionCountdown, setCompletionCountdown] = useState(5);

  useEffect(() => {
    if (stage === "completed") {
      setShowCompletionModal(true);
      setCompletionCountdown(5);
    }
  }, [stage]);

  // Auto-redirect countdown
  useEffect(() => {
    if (!showCompletionModal) return;

    if (completionCountdown <= 0) {
      onExit();
      return;
    }

    const timer = setTimeout(() => {
      setCompletionCountdown((prev) => prev - 1);
    }, 1000);

    return () => clearTimeout(timer);
  }, [showCompletionModal, completionCountdown, onExit]);

  // 自由发言阶段：真人玩家尚未发言时弹出提醒（每次阶段仅一次）
  useEffect(() => {
    if (stage !== "free_discussion") {
      setSpeechReminderShown(false);
      return;
    }
    if (
      !isStreaming &&
      !isProcessingReactions &&
      !speechReminderShown &&
      currentSpeakerId === null
    ) {
      const humanState = playerStates.find(
        (p) => p.character_id === humanCharacterId
      );

      const humanHasRemaining =
        humanState && (humanState.remaining_speech_count ?? 0) > 0;
      const humanNotSpoken = humanState && !humanState.has_spoken_this_round;

      if (humanHasRemaining && humanNotSpoken) {
        setShowSpeechReminder(true);
        setSpeechReminderShown(true);
      }
    }
  }, [
    stage,
    isStreaming,
    isProcessingReactions,
    currentSpeakerId,
    playerStates,
    humanCharacterId,
    speechReminderShown,
  ]);

  // Auto-trigger AI speech when it's AI's turn (and hasn't spoken yet)
  useEffect(() => {
    if (
      !isStreaming &&
      !isProcessingReactions &&
      currentSpeakerId &&
      currentSpeakerId !== humanCharacterId &&
      (stage === "intro" ||
        stage === "clue_analysis" ||
        stage === "free_discussion" ||
        stage === "summary")
    ) {
      // Check if this AI can speak
      const speakerState = playerStates.find(
        (p) => p.character_id === currentSpeakerId
      );

      // For free discussion: check remaining_speech_count
      // For other stages: check has_spoken_this_round (each player speaks once per stage)
      if (stage === "free_discussion") {
        if (speakerState && speakerState.remaining_speech_count <= 0) {
          return;
        }
      } else {
        if (speakerState?.has_spoken_this_round) {
          return;
        }
      }

      // Small delay before AI starts speaking
      const timer = setTimeout(() => {
        triggerAISpeak(currentSpeakerId);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [
    currentSpeakerId,
    humanCharacterId,
    isStreaming,
    isProcessingReactions,
    stage,
    triggerAISpeak,
    playerStates,
  ]);

  // Handle stage transition completion
  const handleTransitionComplete = useCallback(() => {
    setStageTransition(false);
  }, [setStageTransition]);

  // Handle human message send
  const handleSendMessage = useCallback(
    async (content: string) => {
      // Get human character info for optimistic update
      const humanChar = characters.find(
        (c) => c.character_id === humanCharacterId
      );

      // Optimistically add the message to records immediately
      const optimisticRecord: GameRecord = {
        id: Date.now(), // temporary ID
        session_id: sessionId,
        stage: stage,
        speaker_id: humanCharacterId || undefined,
        speaker_name: humanChar?.name || "你",
        content: content,
        record_type: "speech",
        created_at: new Date().toISOString(),
      };
      addRecord(optimisticRecord);

      // Send to backend
      await humanSpeak(content);
    },
    [humanSpeak, characters, humanCharacterId, stage, sessionId, addRecord]
  );

  // Handle stage advance
  const handleAdvanceStage = useCallback(async () => {
    const transition = await advanceStage();
    if (transition) {
      setPreviousStage(transition.from_stage);
    }
  }, [advanceStage]);

  // Handle vote submission
  const handleVote = useCallback(
    async (suspectId: string, suspectName: string, reasoning?: string) => {
      await submitVote(suspectId, suspectName, reasoning);
    },
    [submitVote]
  );

  // Check if it's human's turn to speak
  // 自由发言阶段：只要玩家还有发言次数就可以发言
  const humanPlayerState = playerStates.find(
    (p) => p.character_id === humanCharacterId
  );
  const humanRemainingSpeeches = humanPlayerState?.remaining_speech_count ?? 0;

  const hasHumanTurn =
    currentSpeakerId === humanCharacterId ||
    (stage === "free_discussion" && humanRemainingSpeeches > 0);

  // 自由发言阶段：所有玩家是否都已发言至少一次（可提前推进）
  const allPlayersSpokenOnce =
    stage === "free_discussion" &&
    playerStates.length > 0 &&
    playerStates.every((p) => p.has_spoken_this_round);

  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <GameHeader
        stage={stage}
        currentRound={currentRound}
        scriptTitle={script?.title || "加载中..."}
        onOpenScript={() => setShowScriptModal(true)}
        onSettings={() => setShowSettings(true)}
        onExit={onExit}
      />

      {/* Main Game Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Character Panel */}
        <div className="hidden lg:block w-64 p-4 pt-24 border-r border-border/30">
          <CharacterPanel
            stage={stage}
            characters={characters}
            playerStates={playerStates}
            currentSpeakerId={currentSpeakerId}
            humanCharacterId={humanCharacterId}
            side="left"
          />
        </div>

        {/* Center Chat Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <ChatArea
            records={records}
            characters={characters}
            humanCharacterId={humanCharacterId}
            currentSpeakerId={currentSpeakerId}
            stage={stage}
            isStreaming={isStreaming}
            isProcessingReactions={isProcessingReactions}
            isAdvancingStage={isAdvancingStage}
            streamingSpeakerId={streamingSpeakerId}
            hasHumanTurn={hasHumanTurn}
            agentLlmInfo={agentLlmInfo}
            humanRemainingSpeechCount={humanRemainingSpeeches}
            pendingHumanSpeech={pendingHumanSpeech}
            setPendingHumanSpeech={setPendingHumanSpeech}
            onSendMessage={handleSendMessage}
            onAdvanceStage={handleAdvanceStage}
            onEndGame={() => endGame().then(onExit)}
            canAdvanceEarly={allPlayersSpokenOnce}
          />
        </div>

        {/* Right Character Panel */}
        <div className="hidden lg:block w-64 p-4 pt-24 border-l border-border/30">
          <CharacterPanel
            stage={stage}
            characters={characters}
            playerStates={playerStates}
            currentSpeakerId={currentSpeakerId}
            humanCharacterId={humanCharacterId}
            side="right"
          />
        </div>
      </div>

      {/* Mobile Character Indicators */}
      <div className="lg:hidden fixed bottom-20 left-0 right-0 px-4">
        <div className="flex justify-center gap-2 overflow-x-auto py-2">
          {characters.map((char) => {
            const isSpeaking = currentSpeakerId === char.character_id;
            const isHuman = humanCharacterId === char.character_id;

            return (
              <motion.div
                key={char.character_id}
                whileHover={{ scale: 1.1 }}
                className={`relative w-10 h-10 rounded-full shrink-0 flex items-center justify-center
                  ${isSpeaking ? "breathing ring-2 ring-primary" : ""}
                  bg-gradient-to-br from-primary/30 to-accent/30`}
              >
                {char.avatar_url ? (
                  <img
                    src={char.avatar_url}
                    alt={char.name}
                    className="w-full h-full rounded-full object-cover"
                  />
                ) : (
                  <span className="text-sm font-bold">{char.name[0]}</span>
                )}
                {isHuman && (
                  <div
                    className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-accent
                                flex items-center justify-center text-[10px]"
                  >
                    你
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Stage Transition Overlay */}
      <StageTransitionOverlay
        show={showStageTransition}
        fromStage={previousStage}
        toStage={stage}
        message={stageTransitionMessage}
        onComplete={handleTransitionComplete}
      />

      {/* Voting Modal */}
      <VotingModal
        open={showVotingModal}
        characters={characters}
        humanCharacterId={humanCharacterId}
        existingVotes={votes}
        voteResults={voteResults}
        onVote={handleVote}
        onFinalize={finalizeVoting}
        onClose={() => setShowVotingModal(false)}
      />

      {/* Script Modal */}
      {showScriptModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card rounded-xl p-6 max-w-lg">
            <h3 className="text-lg font-bold mb-4">{script?.title}</h3>
            <p className="text-muted-foreground">{script?.description}</p>
            <button
              onClick={() => setShowScriptModal(false)}
              className="mt-4 px-4 py-2 rounded-lg bg-primary text-primary-foreground"
            >
              关闭
            </button>
          </div>
        </div>
      )}

      {/* Speech Reminder Modal */}
      <AnimatePresence>
        {showSpeechReminder && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => setShowSpeechReminder(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="bg-card rounded-xl p-6 max-w-sm w-full text-center shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-bold mb-3">发言提醒</h3>
              <p className="text-sm text-muted-foreground mb-6 leading-relaxed">
                自由讨论阶段，每位玩家（包括您）至少需要进行一次发言，游戏才可以正常推进。
              </p>
              <button
                onClick={() => setShowSpeechReminder(false)}
                className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium
                         hover:bg-primary/90 transition-colors"
              >
                我知道了
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Game Completion Modal */}
      <AnimatePresence>
        {showCompletionModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="bg-card rounded-xl p-8 max-w-md w-full text-center shadow-2xl"
            >
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-primary/20 flex items-center justify-center">
                <span className="text-3xl">🎉</span>
              </div>
              <h3 className="text-2xl font-bold mb-2">游戏结束</h3>
              <p className="text-muted-foreground mb-6">
                感谢游玩「{script?.title || "剧本杀"}」！
              </p>
              <button
                onClick={onExit}
                className="w-full px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium
                         hover:bg-primary/90 transition-colors"
              >
                返回首页 ({completionCountdown}s)
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Settings Modal */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} />
        )}
      </AnimatePresence>

      {/* Player Script Tooltip */}
      <PlayerScriptTooltip
        scriptContent={humanCharacterScript}
        characterName={
          characters.find((c) => c.character_id === humanCharacterId)?.name
        }
        sessionId={sessionId}
      />

      {/* Draft Notebook */}
      <DraftNotebook sessionId={sessionId} />
    </div>
  );
}
