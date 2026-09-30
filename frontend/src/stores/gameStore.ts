import { create } from 'zustand';
import type {
  GameState,
  PublicClue,
  GameRecord,
  Character,
  Script,
  VoteResults,
  StageTransition,
  GameStateResponse,
} from '@/types/game';
import { gameApi, voteApi } from '@/lib/api';
import { speechClues } from '@/lib/clueScope';
import { OperationRegistry } from '@/lib/operationRegistry';
import { applyGameSnapshot, cancelTurnSubscription, mergeGameRecords, queueHumanSpeech, resumeSpeech, retrySpeech, startSpeech } from '@/lib/gameTurnCoordinator';

const operations = new OperationRegistry();

const appliesToSession = (getState: () => GameState, sessionId: string) =>
  getState().sessionId === sessionId;

interface GameActions {
  // Session management
  initializeGame: (sessionId: string) => Promise<boolean>;
  reset: () => void;
  cancelActiveOperations: () => void;

  // Stage control
  advanceStage: () => Promise<StageTransition | null>;
  acknowledgeCluePresentation: (presentationId: string) => Promise<void>;

  // Speech
  humanSpeak: (content: string) => Promise<void>;
  triggerAISpeak: (characterId: string, retryGenerationId?: string) => Promise<void>;

  // Voting
  submitVote: (suspectId: string, suspectName: string, reasoning?: string) => Promise<void>;
  finalizeVoting: () => Promise<void>;
  endGame: () => Promise<void>;

  // State updates
  updateFromAPI: (data: GameStateResponse) => void;
  resumeActiveTurn: () => Promise<void>;
  retryActiveTurn: () => Promise<void>;
  addRecord: (record: GameRecord) => void;
  setStreaming: (isStreaming: boolean, content?: string, speakerId?: string) => void;
  setStageTransition: (show: boolean, message?: string) => void;
  setCharacters: (characters: Character[]) => void;
  setScript: (script: Script) => void;
  setVoteResults: (results: VoteResults | null) => void;
  setHumanCharacterScript: (script: string) => void;
  setPendingHumanSpeech: (speech: string | null, clues?: PublicClue[]) => void;
}

const initialState: GameState = {
  speechGeneration: null,
  speechConnectionError: '',
  stateRevision: 0,
  activeTurn: null,
  isReconnecting: false,
  pendingHumanRequestId: null,
  // Session info
  sessionId: null,
  scriptId: '',
  humanCharacterId: null,
  humanCharacterScript: '',

  // Game state
  status: 'waiting',
  stage: 'loading',
  currentRound: 0,

  // Data
  script: null,
  characters: [],
  playerStates: [],
  records: [],
  publicClues: [],
  cluePresentation: null,
  clueAssetPreload: [],
  currentSpeakerId: null,
  speechQueue: [],
  agentLlmInfo: {}, // character_id -> { model, provider, is_human }

  // Voting
  votes: {},
  voteResults: null,
  isFinalizingVotes: false,

  // UI state
  isLoading: false,
  isStreaming: false,
  isProcessingReactions: false,
  isAdvancingStage: false, // 推进阶段的loading状态
  streamingContent: '',
  streamingClues: [],
  pendingHumanClues: [],
  streamingSpeakerId: null,
  thinkingTip: '', // 工具调用时的提示信息（显示在流式消息上方）
  showStageTransition: false,
  stageTransitionMessage: '',
  pendingHumanSpeech: null, // 自由发言阶段待发送的真人发言
};

export const useGameStore = create<GameState & GameActions>((set, get) => ({
  ...initialState,

  initializeGame: async (sessionId: string) => {
    operations.abortAll();
    cancelTurnSubscription();
    const controller = operations.start("initialize");
    const current = () => operations.isCurrent("initialize", controller) && appliesToSession(get, sessionId);
    set({ ...initialState, sessionId, isLoading: true });
    try {
      const state = await gameApi.getGameState(sessionId);
      if (!current()) return false;
      if (!state.success) throw new Error("Game state unavailable");
      const historyResponse = await gameApi.getGameHistory(sessionId);
      if (!current()) return false;
      if (!historyResponse.success) throw new Error("Game history unavailable");
      applyGameSnapshot(get, set, state, historyResponse.records || []);
      void resumeSpeech(get, set);
      return true;
    } catch (error) {
      console.error('Failed to initialize game:', error);
      return false;
    } finally {
      if (current()) set({ isLoading: false });
      operations.finish("initialize", controller);
    }
  },

  reset: () => {
    // Abort all in-flight SSE streams before resetting state
    operations.abortAll();
    cancelTurnSubscription();
    set(initialState);
  },

  cancelActiveOperations: () => {
    operations.abortAll();
    cancelTurnSubscription();
    // Detaching a view does not delete a message or cancel the server's turn.
    set({ isLoading: false, isAdvancingStage: false, showStageTransition: false });
  },

  advanceStage: async () => {
    if (get().cluePresentation?.status === 'pending') return null;
    const { sessionId, isAdvancingStage, activeTurn } = get();
    if (!sessionId || isAdvancingStage || activeTurn) return null;
    const controller = operations.start('advance');
    const current = () => operations.isCurrent('advance', controller) && appliesToSession(get, sessionId);
    set({ isAdvancingStage: true });

    try {
      const result = await gameApi.advanceStage(sessionId);
      if (!current()) return null;
      if (result.success && result.transition) {
        const [state, history] = await Promise.all([
          gameApi.getGameState(sessionId), gameApi.getGameHistory(sessionId),
        ]);
        if (!current()) return null;
        applyGameSnapshot(get, set, state, history.records || []);
        set({
          showStageTransition: state.clue_presentation?.status !== 'pending',
          stageTransitionMessage: result.transition.message || '',
        });
        return result.transition;
      }
    } catch (error) {
      console.error('Failed to advance stage:', error);
    } finally {
      if (current()) set({ isAdvancingStage: false });
      operations.finish('advance', controller);
    }
    return null;
  },

  humanSpeak: async (content: string) => {
    if (get().cluePresentation?.status === 'pending') return;
    const speaker = get().humanCharacterId;
    if (speaker) await startSpeech(get, set, 'human', speaker, content);
  },

  triggerAISpeak: async (characterId: string) => {
    if (get().cluePresentation?.status === 'pending') return;
    await startSpeech(get, set, 'ai', characterId);
  },
  resumeActiveTurn: () => resumeSpeech(get, set),
  retryActiveTurn: () => retrySpeech(get, set),


  submitVote: async (suspectId: string, suspectName: string, reasoning?: string) => {
    const { sessionId, humanCharacterId } = get();
    if (!sessionId || !humanCharacterId) return;

    await voteApi.submitVote(sessionId, suspectId, suspectName, reasoning);
    if (!appliesToSession(get, sessionId)) return;
    // Update votes in store so VotingModal detects hasAlreadyVoted and triggers finalizeVoting
    set((state) => ({
      votes: {
        ...state.votes,
        [humanCharacterId]: {
          suspect_id: suspectId,
          suspect_name: suspectName,
          reasoning: reasoning || '',
        },
      },
    }));
  },

  acknowledgeCluePresentation: async (presentationId) => {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    const state = await gameApi.acknowledgeCluePresentation(sessionId, presentationId);
    if (!appliesToSession(get, sessionId)) return;
    if (!state.success) throw new Error('确认失败，请重试');
    applyGameSnapshot(get, set, state);
    set({ showStageTransition: false });
  },

  finalizeVoting: async () => {
    const { sessionId } = get();
    if (!sessionId || get().isFinalizingVotes) return;
    const controller = operations.start('voting');
    const current = () => operations.isCurrent('voting', controller) && appliesToSession(get, sessionId);

    set({ isFinalizingVotes: true });

    try {
      // Single request: backend collects AI votes, tallies results, advances to review
      const result = await voteApi.finalizeVoting(sessionId);
      if (!current()) return;
      if (result.success) {
        const [state, history] = await Promise.all([gameApi.getGameState(sessionId), gameApi.getGameHistory(sessionId)]);
        if (!current()) return;
        applyGameSnapshot(get, set, state, history.records || []);
        set({
          showStageTransition: true,
          stageTransitionMessage: '投票已统计完毕，真相即将揭晓',
        });
      }
    } catch (error) {
      console.error('Failed to finalize voting:', error);
    } finally {
      if (current()) set({ isFinalizingVotes: false });
      operations.finish('voting', controller);
    }
  },

  endGame: async () => {
    const { sessionId } = get();
    if (!sessionId) return;

    try {
      await gameApi.endGame(sessionId);
      if (!appliesToSession(get, sessionId)) return;
      set({ stage: 'completed', status: 'completed' });
    } catch (error) {
      console.error('Failed to end game:', error);
    }
  },

  updateFromAPI: (data) => applyGameSnapshot(get, set, data),

  addRecord: (record: GameRecord) => {
    set((state) => ({
      records: mergeGameRecords(state.records, [record]),
    }));
  },

  setStreaming: (isStreaming: boolean, content = '', speakerId: string | undefined = undefined) => {
    set({
      isStreaming,
      streamingClues: isStreaming && !get().isStreaming ? speechClues(get().stage, get().publicClues) : get().streamingClues,
      streamingContent: content,
      streamingSpeakerId: speakerId ?? null,
    });
  },

  setStageTransition: (show: boolean, message = '') => {
    set({
      showStageTransition: show,
      stageTransitionMessage: message,
    });
  },

  setCharacters: (characters: Character[]) => {
    set({ characters });
  },

  setScript: (script: Script) => {
    set({ script, scriptId: script.script_id });
  },

  setVoteResults: (results: VoteResults | null) => {
    set({ voteResults: results });
  },

  setHumanCharacterScript: (script: string) => {
    set({ humanCharacterScript: script });
  },

  setPendingHumanSpeech: (speech: string | null, clues?: PublicClue[]) => {
    queueHumanSpeech(get, set, speech, clues);
  },
}));
