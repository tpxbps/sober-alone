import { create } from 'zustand';
import type {
  GameState,
  GameRecord,
  PlayerState,
  Character,
  Script,
  VoteResults,
  GameStage,
  StageTransition,
} from '@/types/game';
import { gameApi, speechApi, voteApi } from '@/lib/api';

// Active AbortControllers for cancelling in-flight SSE streams
const _activeControllers = new Map<string, AbortController>();

interface GameActions {
  // Session management
  initializeGame: (sessionId: string) => Promise<void>;
  reset: () => void;
  cancelActiveOperations: () => void;

  // Stage control
  advanceStage: () => Promise<StageTransition | null>;

  // Speech
  humanSpeak: (content: string) => Promise<void>;
  triggerAISpeak: (characterId: string) => Promise<void>;

  // Voting
  submitVote: (suspectId: string, suspectName: string, reasoning?: string) => Promise<void>;
  finalizeVoting: () => Promise<void>;
  endGame: () => Promise<void>;

  // State updates
  updateFromAPI: (data: {
    session_id: string;
    status: string;
    current_stage: GameStage;
    current_round: number;
    player_states: PlayerState[];
    current_speaker_id?: string;
    next_speaker_id?: string;
    speech_queue: string[];
    has_all_spoken: boolean;
  }) => void;
  addRecord: (record: GameRecord) => void;
  setStreaming: (isStreaming: boolean, content?: string, speakerId?: string) => void;
  setStageTransition: (show: boolean, message?: string) => void;
  setCharacters: (characters: Character[]) => void;
  setScript: (script: Script) => void;
  setVoteResults: (results: VoteResults | null) => void;
  setHumanCharacterScript: (script: string) => void;
  setPendingHumanSpeech: (speech: string | null) => void;
}

const initialState: GameState = {
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
  streamingSpeakerId: null,
  thinkingTip: '', // 工具调用时的提示信息（显示在流式消息上方）
  showStageTransition: false,
  stageTransitionMessage: '',
  pendingHumanSpeech: null, // 自由发言阶段待发送的真人发言
};

export const useGameStore = create<GameState & GameActions>((set, get) => ({
  ...initialState,

  initializeGame: async (sessionId: string) => {
    // Full reset to prevent state pollution from previous sessions
    for (const controller of _activeControllers.values()) {
      try { controller.abort(); } catch { /* ignore */ }
    }
    _activeControllers.clear();
    set({ ...initialState, sessionId, isLoading: true });
    try {
      const state = await gameApi.getGameState(sessionId);

      // Extract characters from response
      const characters: Character[] = (state.characters || []).map((c: {
        character_id: string;
        name: string;
        gender?: string;
        age?: number;
        occupation?: string;
        profile?: string;
        avatar_url?: string;
        is_human?: boolean;
        character_script?: string;
        character_script_summary?: string;
      }) => ({
        character_id: c.character_id,
        name: c.name,
        gender: c.gender || '未知',
        age: c.age || 0,
        occupation: c.occupation || '',
        profile: c.profile || '',
        avatar_url: c.avatar_url || '',
        is_human: c.is_human,
        character_script: c.character_script,
        character_script_summary: c.character_script_summary,
      }));

      // Find human character ID and script
      const humanChar = state.characters?.find((c: { is_human?: boolean }) => c.is_human);
      const humanCharacterId = state.human_character_id || humanChar?.character_id || null;
      const humanCharacterScript = humanChar?.character_script || '';

      // Extract script data
      const script: Script | null = state.script ? {
        script_id: state.script.script_id,
        title: state.script.title,
        description: state.script.description || '',
        overview: state.script.overview || '',
        tags: state.script.tags || '',
        difficulty: state.script.difficulty || 1,
        player_count: state.script.player_count || 0,
        estimated_duration: 0,
        cover_image_url: state.script.cover_image_url,
      } : null;

      set({
        status: state.status as GameState['status'],
        stage: state.current_stage,
        currentRound: state.current_round,
        playerStates: state.player_states || [],
        currentSpeakerId: state.current_speaker_id || null,
        speechQueue: state.speech_queue || [],
        characters,
        humanCharacterId,
        humanCharacterScript,
        script,
        scriptId: script?.script_id || '',
        agentLlmInfo: state.agent_llm_info || (state.llm_configs ? Object.fromEntries(
          Object.entries(state.llm_configs).map(([k, v]) => [k, { ...v, is_human: false }])
        ) : {}),
      });

      // Load history
      const historyResponse = await gameApi.getGameHistory(sessionId);
      set({ records: historyResponse.records || [] });
    } catch (error) {
      console.error('Failed to initialize game:', error);
    } finally {
      set({ isLoading: false });
    }
  },

  reset: () => {
    // Abort all in-flight SSE streams before resetting state
    for (const controller of _activeControllers.values()) {
      try { controller.abort(); } catch { /* ignore */ }
    }
    _activeControllers.clear();
    set(initialState);
  },

  cancelActiveOperations: () => {
    // Abort all in-flight SSE streams
    for (const controller of _activeControllers.values()) {
      try { controller.abort(); } catch { /* ignore */ }
    }
    _activeControllers.clear();
    // Reset UI flags that could block the next session
    set({
      isStreaming: false,
      isProcessingReactions: false,
      isAdvancingStage: false,
      streamingContent: '',
      streamingSpeakerId: null,
      thinkingTip: '',
      showStageTransition: false,
      stageTransitionMessage: '',
      pendingHumanSpeech: null,
      isLoading: false,
    });
  },

  advanceStage: async () => {
    const { sessionId, isAdvancingStage } = get();
    if (!sessionId || isAdvancingStage) return null;

    set({ isAdvancingStage: true });

    try {
      const result = await gameApi.advanceStage(sessionId);
      if (result.success && result.transition) {
        // 重新加载游戏状态
        const state = await gameApi.getGameState(sessionId);

        set({
          stage: result.transition.to_stage,
          showStageTransition: true,
          stageTransitionMessage: result.transition.message || '',
          currentSpeakerId: state.current_speaker_id || null,
          speechQueue: state.speech_queue || [],
          playerStates: state.player_states || [],
          currentRound: state.current_round,
          isAdvancingStage: false,
        });

        // 重新加载历史记录
        const historyResponse = await gameApi.getGameHistory(sessionId);
        set({ records: historyResponse.records || [] });

        return result.transition;
      }
      set({ isAdvancingStage: false });
    } catch (error) {
      console.error('Failed to advance stage:', error);
      set({ isAdvancingStage: false });
    }
    return null;
  },

  humanSpeak: async (content: string) => {
    const { sessionId } = get();
    if (!sessionId) return;

    // Register AbortController for this SSE stream
    const controller = new AbortController();
    _activeControllers.set('human-speak', controller);

    // 设置正在处理反应状态
    set({ isProcessingReactions: true });

    try {
      const response = await speechApi.humanSpeakStream(sessionId, content, controller.signal);
      const stream = speechApi.processSSEStream(response, controller.signal);

      let nextSpeakerId: string | null = null;

      for await (const message of stream) {

        if (message.type === 'thinking') {
          // 更新thinking提示
          set({ thinkingTip: message.message || '' });
        } else if (message.type === 'reactions_done') {
          // Reactions完成
          set({ thinkingTip: '' });
        } else if (message.type === 'done') {
          // 全部完成
          nextSpeakerId = message.next_speaker_id || null;
        } else if (message.type === 'error') {
          throw new Error(message.message || '发言失败');
        }
      }

      // 重新加载状态
      const [historyResponse, state] = await Promise.all([
        gameApi.getGameHistory(sessionId),
        gameApi.getGameState(sessionId),
      ]);

      set({
        records: historyResponse.records,
        currentSpeakerId: nextSpeakerId || state.current_speaker_id || null,
        speechQueue: state.speech_queue,
        playerStates: state.player_states,
        isProcessingReactions: false,
        thinkingTip: '',
      });
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.error('Failed to send message:', error);
      set({ isProcessingReactions: false, thinkingTip: '' });
    } finally {
      _activeControllers.delete('human-speak');
    }
  },

  triggerAISpeak: async (characterId: string) => {
    const { sessionId } = get();
    if (!sessionId) return;

    // Register AbortController for this SSE stream
    const controller = new AbortController();
    _activeControllers.set(`ai-speak-${characterId}`, controller);

    set({ isStreaming: true, streamingContent: '', streamingSpeakerId: characterId, thinkingTip: '' });

    try {
      const response = await speechApi.aiSpeakStream(sessionId, characterId, controller.signal);
      const stream = speechApi.processSSEStream(response, controller.signal);

      let fullContent = '';
      // RAF buffer: batch token updates to at most once per animation frame
      let rafId: number | null = null;
      let lastFlushedContent = '';
      const flushContent = () => {
        rafId = null;
        if (fullContent !== lastFlushedContent) {
          lastFlushedContent = fullContent;
          set({ streamingContent: fullContent, thinkingTip: '' });
        }
      };

      for await (const message of stream) {
        // Handle different message types from backend
        if (message.type === 'token') {
          // Backend sends {type: "token", text: "..."}
          const token = (message as unknown as { text?: string }).text || '';
          fullContent += token;
          if (rafId === null) {
            rafId = requestAnimationFrame(flushContent);
          }
        } else if (message.type === 'thinking') {
          // AI is thinking/using tools - show thinking tip ABOVE streaming content
          const thinkingMessage = message?.message || '正在思考...';
          set({ thinkingTip: thinkingMessage });
        } else if (message.type === 'speech_done') {
          // Flush any pending RAF buffer before transitioning state
          if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
          }
          set({
            isStreaming: false,
            streamingContent: fullContent, // Ensure final content is flushed
            isProcessingReactions: true,
            thinkingTip: '',
          });
        } else if (message.type === 'done') {
          // Flush RAF buffer
          if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
          }
          // All processing complete (speech + reactions broadcast)
          let nextSpeakerId = message?.next_speaker_id || null;

          // 检查是否有待发送的真人发言（自由发言阶段）
          const { pendingHumanSpeech, stage, streamingContent: aiFinalContent, streamingSpeakerId: aiSpeakerId, records: currentRecords, humanCharacterId } = get();

          if (stage === 'free_discussion' && pendingHumanSpeech) {
            // 有待发送的真人发言

            // 0. 乐观更新：立即将AI的最后发言和真人的发言添加到records
            const optimisticRecords = [...currentRecords];
            // 添加AI的最后一段发言
            if (aiFinalContent && aiSpeakerId) {
              const aiCharName = get().characters.find(c => c.character_id === aiSpeakerId)?.name || 'AI';
              optimisticRecords.push({
                id: Date.now(),
                session_id: sessionId,
                speaker_id: aiSpeakerId,
                speaker_name: aiCharName,
                content: aiFinalContent,
                record_type: 'speech',
                stage: stage,
                created_at: new Date().toISOString(),
              });
            }
            // 添加真人的发言
            if (humanCharacterId) {
              const humanCharName = get().characters.find(c => c.character_id === humanCharacterId)?.name || '你';
              optimisticRecords.push({
                id: Date.now() + 1,
                session_id: sessionId,
                speaker_id: humanCharacterId,
                speaker_name: humanCharName,
                content: pendingHumanSpeech,
                record_type: 'speech',
                stage: stage,
                created_at: new Date().toISOString(),
              });
            }

            // 1. 清除待发送状态和流式状态，设置reaction状态
            set({
              pendingHumanSpeech: null,
              currentSpeakerId: null,
              isStreaming: false,
              streamingContent: '',
              streamingSpeakerId: null,
              isProcessingReactions: true,
              thinkingTip: '',
              records: optimisticRecords,
            });

            // 2. 发送真人发言（流式）
            try {
              const humanResponse = await speechApi.humanSpeakStream(sessionId, pendingHumanSpeech);
              const humanStream = speechApi.processSSEStream(humanResponse);

              for await (const humanMsg of humanStream) {
                if (humanMsg.type === 'thinking') {
                  set({ thinkingTip: humanMsg.message || '' });
                } else if (humanMsg.type === 'done') {
                  nextSpeakerId = humanMsg.next_speaker_id || null;
                }
              }
            } catch (e) {
              console.error('[ERROR] Pending human speech failed:', e);
            }

            // 3. 重新加载状态
            const [historyResponse, state] = await Promise.all([
              gameApi.getGameHistory(sessionId),
              gameApi.getGameState(sessionId),
            ]);
            set({
              records: historyResponse.records,
              speechQueue: state.speech_queue,
              playerStates: state.player_states,
              currentSpeakerId: nextSpeakerId || state.current_speaker_id || null,
            });
            return;
          }

          // 正常处理：更新当前发言者为下一位
          set({
            currentSpeakerId: nextSpeakerId,
            isStreaming: false,
            streamingContent: '',
            streamingSpeakerId: null,
            isProcessingReactions: false,
            thinkingTip: '',
          });

          // Reload history and state in background
          const [historyResponse, state] = await Promise.all([
            gameApi.getGameHistory(sessionId),
            gameApi.getGameState(sessionId),
          ]);
          set({
            records: historyResponse.records,
            speechQueue: state.speech_queue,
            playerStates: state.player_states,
          });
          return;
        } else if (message.type === 'error') {
          console.error('Stream error:', (message as unknown as { message?: string }).message || message);
          break;
        }
      }
      // Clean up any remaining RAF
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    } catch (error: unknown) {
      // Silently ignore abort errors (session was reset/changed)
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.error('Failed to trigger AI speak:', error);
    } finally {
      _activeControllers.delete(`ai-speak-${characterId}`);
      // Only update state if this controller wasn't aborted (i.e. still the active session)
      if (!controller.signal.aborted) {
        set({ isStreaming: false, streamingContent: '', streamingSpeakerId: null, isProcessingReactions: false, thinkingTip: '' });
      }
    }
  },

  submitVote: async (suspectId: string, suspectName: string, reasoning?: string) => {
    const { sessionId, humanCharacterId } = get();
    if (!sessionId || !humanCharacterId) return;

    try {
      await voteApi.submitVote(sessionId, suspectId, suspectName, reasoning);
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
    } catch (error) {
      console.error('Failed to submit vote:', error);
    }
  },

  finalizeVoting: async () => {
    const { sessionId } = get();
    if (!sessionId) return;

    set({ isFinalizingVotes: true });

    try {
      // Single request: backend collects AI votes, tallies results, advances to review
      const result = await voteApi.finalizeVoting(sessionId);
      if (result.success) {
        // 重新加载历史记录（包含投票记录、复盘消息等）
        const historyResponse = await gameApi.getGameHistory(sessionId);
        set((state) => ({
          voteResults: result.vote_results,
          stage: result.transition.to_stage as GameStage,
          records: historyResponse.records || state.records,
          showStageTransition: true,
          stageTransitionMessage: '投票已统计完毕，真相即将揭晓',
          isFinalizingVotes: false,
        }));
      } else {
        set({ isFinalizingVotes: false });
      }
    } catch (error) {
      console.error('Failed to finalize voting:', error);
      set({ isFinalizingVotes: false });
    }
  },

  endGame: async () => {
    const { sessionId } = get();
    if (!sessionId) return;

    try {
      await gameApi.endGame(sessionId);
      set({ stage: 'completed', status: 'completed' });
    } catch (error) {
      console.error('Failed to end game:', error);
    }
  },

  updateFromAPI: (data) => {
    set({
      sessionId: data.session_id,
      status: data.status as GameState['status'],
      stage: data.current_stage,
      currentRound: data.current_round,
      playerStates: data.player_states,
      currentSpeakerId: data.current_speaker_id || null,
      speechQueue: data.speech_queue,
    });
  },

  addRecord: (record: GameRecord) => {
    set((state) => ({
      records: [...state.records, record],
    }));
  },

  setStreaming: (isStreaming: boolean, content = '', speakerId: string | undefined = undefined) => {
    set({
      isStreaming,
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

  setPendingHumanSpeech: (speech: string | null) => {
    set({ pendingHumanSpeech: speech });
  },
}));
