import { CharacterPreview } from "@/components/game/CharacterPreview";
import { gameApi } from "@/lib/api";
import { useState, useEffect, useCallback, useRef } from "react";
import { AnimatePresence } from "framer-motion";
import { FileEdit, BookOpen } from "lucide-react";

import { useGameStore } from "@/stores/gameStore";
import { useShallow } from "zustand/react/shallow";
import { GameHeader } from "@/components/game/GameHeader";
import { CharacterPanel } from "@/components/game/CharacterPanel";
import { ChatArea } from "@/components/game/ChatArea";
import { VotingModal } from "@/components/game/VotingModal";
import { StageTransitionOverlay } from "@/components/game/StageTransitionOverlay";
import { PersonalScriptHint } from "@/components/game/PersonalScriptHint";
import { usePersonalScriptRead } from "@/hooks/usePersonalScriptRead";
import { PlayerScriptTooltip } from "@/components/game/PlayerScriptTooltip";
import { DraftNotebook } from "@/components/game/DraftNotebook";
import { SettingsModal } from "@/components/SettingsModal";
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogClose } from "@/components/ui/dialog";
import { Markdown } from "@/components/ui/Markdown";
import type { Character, GameStage, GameRecord } from "@/types/game";
import { resolveDisplayedSpeakerId } from "@/lib/speakerPresentation";
import { citedIds, speechClues } from "@/lib/clueScope";

interface GamePageProps {
  sessionId: string;
  onExit: () => void;
}

export function GamePage({ sessionId, onExit }: GamePageProps) {
  const [votingDismissedRound, setVotingDismissedRound] = useState<string | null>(null);
  const [showScriptModal, setShowScriptModal] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showSpeechReminder, setShowSpeechReminder] = useState(false);
  const speechReminderRoundRef = useRef<string | null>(null);
  const [previousStage, setPreviousStage] = useState<GameStage | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [pauseAutoSpeak, setPauseAutoSpeak] = useState({
    context: "",
    value: false,
  });
  const [mentionRequest, setMentionRequest] = useState<{
    character: Character;
    nonce: number;
  } | null>(null);
  const mentionNonceRef = useRef(0);
  const { read: scriptOpened } = usePersonalScriptRead(sessionId);
  const scriptHintRef = useRef<HTMLDivElement>(null);


  const {
    // State
    stage,
    currentRound,
    script,
    characters,
    playerStates,
    records,
    publicClues,
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
  } = useGameStore(
    useShallow((s) => ({
      stage: s.stage,
      currentRound: s.currentRound,
      script: s.script,
      characters: s.characters,
      playerStates: s.playerStates,
      records: s.records,
      publicClues: s.publicClues,
      currentSpeakerId: s.currentSpeakerId,
      humanCharacterId: s.humanCharacterId,
      humanCharacterScript: s.humanCharacterScript,
      isStreaming: s.isStreaming,
      isProcessingReactions: s.isProcessingReactions,
      isAdvancingStage: s.isAdvancingStage,
      streamingSpeakerId: s.streamingSpeakerId,
      showStageTransition: s.showStageTransition,
      stageTransitionMessage: s.stageTransitionMessage,
      voteResults: s.voteResults,
      votes: s.votes,
      agentLlmInfo: s.agentLlmInfo,
      pendingHumanSpeech: s.pendingHumanSpeech,
      initializeGame: s.initializeGame,
      advanceStage: s.advanceStage,
      humanSpeak: s.humanSpeak,
      triggerAISpeak: s.triggerAISpeak,
      submitVote: s.submitVote,
      finalizeVoting: s.finalizeVoting,
      endGame: s.endGame,
      setStageTransition: s.setStageTransition,
      addRecord: s.addRecord,
      setPendingHumanSpeech: s.setPendingHumanSpeech,
      cancelActiveOperations: s.cancelActiveOperations,
    }))
  );
  useEffect(() => {
    if (!isProcessingReactions || isStreaming) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const state = await gameApi.getGameState(sessionId);
        if (!cancelled) useGameStore.getState().updateFromAPI(state);
        if (state.turn_processing && !cancelled) timer = setTimeout(poll, 1500);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 3000);
      }
    };
    timer = setTimeout(poll, 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [sessionId, isProcessingReactions, isStreaming]);

  const pauseContextKey = `${sessionId}:${stage}:${currentRound}`;
  const isAutoSpeakPaused =
    pauseAutoSpeak.value && pauseAutoSpeak.context === pauseContextKey;
  const displayedSpeakerId = resolveDisplayedSpeakerId({
    stage,
    isAutoSpeakPaused,
    isStreaming,
    streamingSpeakerId,
    currentSpeakerId,
  });
  const handlePauseAutoSpeakChange = useCallback(
    (value: boolean) => {
      setPauseAutoSpeak({ context: value ? pauseContextKey : "", value });
    },
    [pauseContextKey]
  );

  const handleScriptOpenChange = setScriptOpen;

  // Initialize game
  useEffect(() => {
    if (sessionId && (useGameStore.getState().sessionId !== sessionId || useGameStore.getState().stage === "loading")) {
      void initializeGame(sessionId);
    }

    return () => {
      // Cancel all in-flight SSE streams when GamePage unmounts
      cancelActiveOperations();
    };
  }, [sessionId, initializeGame, cancelActiveOperations]);

  const voteRoundKey = `${stage}:${currentRound}`;
  const hasVoteResults = !!voteResults && Object.keys(voteResults).length > 0;
  const showVotingModal =
    stage === "vote" && !hasVoteResults && votingDismissedRound !== voteRoundKey;

  const humanCharacter = characters.find(character => character.character_id === humanCharacterId);
  const showScriptHint = !!humanCharacterScript && !scriptOpened && stage !== "loading" && stage !== "completed"
    && !showStageTransition && !showScriptModal && !showSettings && !showSpeechReminder
    && !showVotingModal && !draftOpen && !scriptOpen;
  const personalScriptHint = showScriptHint ? <PersonalScriptHint
    name={humanCharacter?.name} summary={humanCharacter?.character_script_summary}
    content={humanCharacterScript} onOpen={() => setScriptOpen(true)} /> : null;

  useEffect(() => {
    const hint = scriptHintRef.current;
    const composer = document.querySelector('[data-game-composer]');
    if (!showScriptHint || !hint || !composer) return;
    // A wider hint may extend into the chat column. Keep it above every input
    // control, including when the composer grows while the player is typing.
    const position = () => {
      hint.style.bottom = `${Math.max(96, window.innerHeight - composer.getBoundingClientRect().top + 16)}px`;
    };
    const observer = new ResizeObserver(position);
    observer.observe(composer);
    window.addEventListener('resize', position);
    position();
    return () => { observer.disconnect(); window.removeEventListener('resize', position); };
  }, [showScriptHint]);

  // Show completion modal when game ends (removed - review stage has end button)
  useEffect(() => {
    if (stage === "completed") {
      onExit();
    }
  }, [stage, onExit]);

  // 自由发言阶段：真人玩家尚未发言时弹出提醒（每次阶段仅一次）
  // 仅在所有AI角色用光发言次数、而真人一次都还没发言时触发
  useEffect(() => {
    if (stage !== "free_discussion") return;
    if (
      !isStreaming &&
      !isProcessingReactions &&
      speechReminderRoundRef.current !== `${stage}:${currentRound}` &&
      currentSpeakerId === null
    ) {
      const humanState = playerStates.find(
        (p) => p.character_id === humanCharacterId
      );

      const humanHasRemaining =
        humanState && (humanState.remaining_speech_count ?? 0) > 0;
      const humanNotSpoken = humanState && !humanState.has_spoken_this_round;

      // 检查是否所有AI角色都已用光发言次数
      const aiStates = playerStates.filter(
        (p) => p.character_id !== humanCharacterId
      );
      const allAIExhausted =
        aiStates.length > 0 &&
        aiStates.every((p) => (p.remaining_speech_count ?? 0) <= 0);

      if (humanHasRemaining && humanNotSpoken && allAIExhausted) {
        speechReminderRoundRef.current = `${stage}:${currentRound}`;
        const timer = window.setTimeout(() => setShowSpeechReminder(true), 0);
        return () => window.clearTimeout(timer);
      }
    }
  }, [
    stage,
    isStreaming,
    isProcessingReactions,
    currentSpeakerId,
    playerStates,
    humanCharacterId,
    currentRound,
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
      && !(stage === "free_discussion" && isAutoSpeakPaused)
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
      // 自由讨论阶段留较长间隔，让玩家有机会点击"直接进入下一阶段"
      const delay = stage === "free_discussion" ? 1500 : 500;
      const timer = setTimeout(() => {
        triggerAISpeak(currentSpeakerId);
      }, delay);
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
    isAutoSpeakPaused,
  ]);

  const handleCharacterMention = useCallback(
    (characterId: string) => {
      if (characterId === humanCharacterId) return;
      const character = characters.find((item) => item.character_id === characterId);
      if (!character) return;
      mentionNonceRef.current += 1;
      setMentionRequest({ character, nonce: mentionNonceRef.current });
    },
    [characters, humanCharacterId]
  );

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
        clue_refs: citedIds(content, speechClues(stage, publicClues)),
        record_type: "speech",
        created_at: new Date().toISOString(),
      };
      addRecord(optimisticRecord);

      // Send to backend
      await humanSpeak(content);
    },
    [humanSpeak, characters, humanCharacterId, stage, sessionId, addRecord, publicClues]
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
    <div className="h-screen flex flex-col scene-screen scene-game overflow-hidden">
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
      <div className="flex-1 overflow-hidden">
        <div className="h-full mx-auto flex max-w-[1800px] px-0 lg:px-4 xl:px-8 2xl:px-12">
        {/* Left Character Panel */}
        <div className="hidden lg:block lg:w-56 xl:w-64 shrink-0 p-2 xl:p-4 pt-24 border-r border-border/30">
          <CharacterPanel
            stage={stage}
            characters={characters}
            playerStates={playerStates}
            currentSpeakerId={displayedSpeakerId}
            humanCharacterId={humanCharacterId}
            side="left"
            onCharacterClick={handleCharacterMention}
          />
        </div>

        {/* Center Chat Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <ChatArea
            records={records}
            characters={characters}
            publicClues={publicClues}
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
            scriptId={script?.script_id}
            onSendMessage={handleSendMessage}
            onAdvanceStage={handleAdvanceStage}
            onEndGame={() => endGame().then(onExit)}
            canAdvanceEarly={allPlayersSpokenOnce}
            mentionRequest={mentionRequest}
            pauseAutoSpeak={isAutoSpeakPaused}
            onPauseAutoSpeakChange={handlePauseAutoSpeakChange}
            onHumanSpeechCompleted={() => handlePauseAutoSpeakChange(false)}
          />

          {personalScriptHint && <div className="personal-script-hint-mobile lg:hidden shrink-0 px-4 pb-2">{personalScriptHint}</div>}

          {/* Mobile Bottom Toolbar - flow-based, NOT fixed */}
          <div className="lg:hidden shrink-0 border-t border-border/30 bg-background/90 backdrop-blur-md px-2 py-1.5">
            <div className="flex items-center gap-2">
              {/* Character avatars - horizontally scrollable */}
              <div className="flex gap-1.5 overflow-x-auto flex-1 py-0.5 scrollbar-hide">
                {characters.map((char) => {
                  const isSpeaking = displayedSpeakerId === char.character_id;
                  const isHuman = humanCharacterId === char.character_id;

                  return (
                    <CharacterPreview key={char.character_id} name={char.name} src={char.portrait_url || char.avatar_url}
                      details={<><h3 className="font-semibold">{char.name}</h3>
                        <p className="mt-2 text-sm text-muted-foreground">{char.profile || "暂无人物简介"}</p>
                        <p className="mt-3 text-xs text-primary">{isSpeaking ? "正在发言" : "等待发言"}</p></>}>
                    <button
                      type="button"
                      disabled={isHuman}
                      onClick={() => handleCharacterMention(char.character_id)}
                      aria-label={isHuman ? `${char.name}（你）` : `在输入框引用 ${char.name}`}
                      className={`relative w-8 h-8 rounded-full shrink-0 flex items-center justify-center
                        ${isSpeaking ? "breathing ring-2 ring-primary" : ""}
                        bg-gradient-to-br from-primary/30 to-accent/30 disabled:cursor-default`}
                    >
                      {char.avatar_url ? (
                        <img
                          src={char.avatar_url}
                          alt={char.name}
                          className="w-full h-full rounded-full object-cover"
                        />
                      ) : (
                        <span className="text-xs font-bold">{char.name[0]}</span>
                      )}
                      {isHuman && (
                        <div
                          className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-accent
                                      flex items-center justify-center text-[8px]"
                        >
                          你
                        </div>
                      )}
                    </button>
                    </CharacterPreview>
                  );
                })}
              </div>

              {/* Divider */}
              <div className="w-px h-6 bg-border/40 shrink-0" />

              {/* Action buttons */}
              <div className="flex gap-1.5 shrink-0">
                <button
                  onClick={() => setDraftOpen(true)}
                  className="w-8 h-8 rounded-full bg-secondary/50 hover:bg-secondary/70
                             flex items-center justify-center transition-colors"
                  title="草稿本"
                >
                  <FileEdit className="w-4 h-4" />
                </button>
                {humanCharacterScript && (
                  <button
                    onClick={() => setScriptOpen(true)}
                    className="relative w-8 h-8 rounded-full bg-primary/80 hover:bg-primary text-primary-foreground
                               flex items-center justify-center transition-colors"
                    data-personal-script-trigger
                    title="查看我的剧本"
                    aria-label="查看我的剧本"
                  >
                    <BookOpen className="w-4 h-4" />
                    {!scriptOpened && (
                      <span className="absolute -top-0.5 -right-0.5 px-1 rounded-full bg-accent text-[7px] font-bold text-accent-foreground">
                        新
                      </span>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Right Character Panel */}
        <div className="hidden lg:block lg:w-56 xl:w-64 shrink-0 p-2 xl:p-4 pt-24 border-l border-border/30">
          <CharacterPanel
            stage={stage}
            characters={characters}
            playerStates={playerStates}
            currentSpeakerId={displayedSpeakerId}
            humanCharacterId={humanCharacterId}
            side="right"
            onCharacterClick={handleCharacterMention}
          />
        </div>
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
        onClose={() => setVotingDismissedRound(voteRoundKey)}
      />

      {/* Shared dialog surfaces keep reading, focus and dismissal consistent. */}
      <Dialog open={showScriptModal} onOpenChange={setShowScriptModal}>
        <DialogContent>
          <DialogTitle className="font-serif text-xl">{script?.title}</DialogTitle>
          <DialogDescription className="sr-only">当前剧本简介</DialogDescription>
          {script?.description && <Markdown className="text-sm text-muted-foreground leading-relaxed">{script.description}</Markdown>}
          <DialogClose asChild><button className="justify-self-start px-4 py-2 rounded-lg bg-primary text-primary-foreground">关闭</button></DialogClose>
        </DialogContent>
      </Dialog>
      <Dialog open={showSpeechReminder} onOpenChange={setShowSpeechReminder}>
        <DialogContent className="sm:max-w-sm">
          <DialogTitle>发言提醒</DialogTitle>
          <DialogDescription>自由讨论阶段，每位玩家（包括您）至少需要进行一次发言，游戏才可以正常推进。</DialogDescription>
          <DialogClose asChild><button className="px-6 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90">我知道了</button></DialogClose>
        </DialogContent>
      </Dialog>

      {/* Game Completion Modal - removed: review stage already has end game button */}

      {/* Settings Modal */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} mode="game" />
        )}
      </AnimatePresence>

      {personalScriptHint && <div ref={scriptHintRef} className="personal-script-hint-desktop hidden lg:block fixed bottom-44 right-6 z-40 w-[clamp(20rem,24vw,30rem)]">{personalScriptHint}</div>}

      {/* Player Script Tooltip */}
      <PlayerScriptTooltip
        scriptContent={humanCharacterScript}
        scriptSummary={
          characters.find((c) => c.character_id === humanCharacterId)
            ?.character_script_summary
        }
        characterName={
          characters.find((c) => c.character_id === humanCharacterId)?.name
        }
        sessionId={sessionId}
        scriptId={script?.resource_namespace || script?.script_id}
        characterId={humanCharacterId || undefined}
        open={scriptOpen}
        onOpenChange={handleScriptOpenChange}
      />

      {/* Draft Notebook */}
      <DraftNotebook
        sessionId={sessionId}
        open={draftOpen}
        onOpenChange={setDraftOpen}
      />
    </div>
  );
}
