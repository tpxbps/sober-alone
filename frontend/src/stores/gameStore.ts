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
import { adaptGameState } from '@/lib/gameStateAdapter';
import { OperationRegistry } from '@/lib/operationRegistry';
import { runSpeechStream } from '@/lib/speechStreamRunner';

const operations = new OperationRegistry();

const appliesToSession = (getState: () => GameState, sessionId: string) =>
  getState().sessionId === sessionId;

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
    operations.abortAll();
    set({ ...initialState, sessionId, isLoading: true });
    try {
      const state = await gameApi.getGameState(sessionId);

      if (!appliesToSession(get, sessionId)) return;
      set(adaptGameState(state));

      // Load history
      const historyResponse = await gameApi.getGameHistory(sessionId);
      if (appliesToSession(get, sessionId)) set({ records: historyResponse.records || [] });
    } catch (error) {
      console.error('Failed to initialize game:', error);
    } finally {
      if (appliesToSession(get, sessionId)) set({ isLoading: false });
    }
  },

  reset: () => {
    // Abort all in-flight SSE streams before resetting state
    operations.abortAll();
    set(initialState);
  },

  cancelActiveOperations: () => {
    // Abort all in-flight SSE streams
    operations.abortAll();
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
          votes: state.votes || {},
          voteResults: state.vote_results || null,
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
    const operationKey = 'human-speak';
    const controller = operations.start(operationKey);

    // 设置正在处理反应状态
    set({ isProcessingReactions: true });

    try {
      const response = await speechApi.humanSpeakStream(sessionId, content, controller.signal);
      const stream = speechApi.processSSEStream(response, controller.signal);

      let nextSpeakerId: string | null = null;

      await runSpeechStream(
        stream,
        {
          thinking: (message) => {
            if (operations.isCurrent(operationKey, controller) && appliesToSession(get, sessionId)) {
              set({ thinkingTip: message.message || '' });
            }
          },
          reactions_done: () => {
            if (operations.isCurrent(operationKey, controller) && appliesToSession(get, sessionId)) {
              set({ thinkingTip: '' });
            }
          },
          done: (message) => {
            nextSpeakerId = message.next_speaker_id || null;
          },
          error: (message) => {
            throw new Error(message.message || '发言失败');
          },
        },
        controller.signal,
      );

      // 重新加载状态
      const [historyResponse, state] = await Promise.all([
        gameApi.getGameHistory(sessionId),
        gameApi.getGameState(sessionId),
      ]);

      if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
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
      if (appliesToSession(get, sessionId)) set({ isProcessingReactions: false, thinkingTip: '' });
    } finally {
      operations.finish(operationKey, controller);
    }
  },

  triggerAISpeak: async (characterId: string) => {
    const { sessionId } = get();
    if (!sessionId) return;

    // Register AbortController for this SSE stream
    const operationKey = `ai-speak-${characterId}`;
    const controller = operations.start(operationKey);

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

      await runSpeechStream(
        stream,
        {
          token: (message) => {
            if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
            fullContent += message.text || '';
            if (rafId === null) rafId = requestAnimationFrame(flushContent);
          },
          thinking: (message) => {
            if (operations.isCurrent(operationKey, controller) && appliesToSession(get, sessionId)) {
              set({ thinkingTip: message.message || '正在思考...' });
            }
          },
          speech_done: () => {
            if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
            if (rafId !== null) {
              cancelAnimationFrame(rafId);
              rafId = null;
            }
            if (fullContent) {
              set({
                isStreaming: false,
                streamingContent: fullContent,
                isProcessingReactions: true,
                thinkingTip: '',
              });
              return;
            }
            const {
              records: currentRecords,
              streamingSpeakerId: speakerId,
              characters: currentCharacters,
              stage: currentStage,
            } = get();
            const fallbackRecord: GameRecord = {
              id: Date.now(),
              session_id: sessionId,
              speaker_id: speakerId || undefined,
              speaker_name: currentCharacters.find((character) => character.character_id === speakerId)?.name || 'AI',
              content: '（系统提示：AI角色出现未知错误，暂时无法正常发言。）',
              record_type: 'speech',
              stage: currentStage,
              created_at: new Date().toISOString(),
            };
            set({
              isStreaming: false,
              streamingContent: '',
              streamingSpeakerId: null,
              isProcessingReactions: true,
              thinkingTip: '',
              records: [...currentRecords, fallbackRecord],
            });
          },
          done: async (message) => {
            if (rafId !== null) {
              cancelAnimationFrame(rafId);
              rafId = null;
            }
            if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
            let nextSpeakerId = message.next_speaker_id || null;
            const {
              pendingHumanSpeech,
              stage,
              streamingContent: aiFinalContent,
              streamingSpeakerId: aiSpeakerId,
              records: currentRecords,
              humanCharacterId,
            } = get();

            if (stage === 'free_discussion' && pendingHumanSpeech) {
              const optimisticRecords = [...currentRecords];
              if (aiFinalContent && aiSpeakerId) {
                const aiName = get().characters.find((character) => character.character_id === aiSpeakerId)?.name || 'AI';
                optimisticRecords.push({
                  id: Date.now(),
                  session_id: sessionId,
                  speaker_id: aiSpeakerId,
                  speaker_name: aiName,
                  content: aiFinalContent,
                  record_type: 'speech',
                  stage,
                  created_at: new Date().toISOString(),
                });
              }
              if (humanCharacterId) {
                const humanName = get().characters.find((character) => character.character_id === humanCharacterId)?.name || '你';
                optimisticRecords.push({
                  id: Date.now() + 1,
                  session_id: sessionId,
                  speaker_id: humanCharacterId,
                  speaker_name: humanName,
                  content: pendingHumanSpeech,
                  record_type: 'speech',
                  stage,
                  created_at: new Date().toISOString(),
                });
              }
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

              try {
                const humanResponse = await speechApi.humanSpeakStream(
                  sessionId,
                  pendingHumanSpeech,
                  controller.signal,
                );
                const humanStream = speechApi.processSSEStream(humanResponse, controller.signal);
                await runSpeechStream(
                  humanStream,
                  {
                    thinking: (humanMessage) => {
                      if (operations.isCurrent(operationKey, controller) && appliesToSession(get, sessionId)) {
                        set({ thinkingTip: humanMessage.message || '' });
                      }
                    },
                    done: (humanMessage) => {
                      nextSpeakerId = humanMessage.next_speaker_id || null;
                    },
                    error: (humanMessage) => {
                      throw new Error(humanMessage.message || '待发送的真人发言失败');
                    },
                  },
                  controller.signal,
                );
              } catch (error) {
                if (!(error instanceof DOMException && error.name === 'AbortError')) {
                  console.error('[ERROR] Pending human speech failed:', error);
                }
              }
            }

            const [historyResponse, state] = await Promise.all([
              gameApi.getGameHistory(sessionId),
              gameApi.getGameState(sessionId),
            ]);
            if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
            set({
              records: historyResponse.records,
              currentSpeakerId: nextSpeakerId || state.current_speaker_id || null,
              speechQueue: state.speech_queue,
              playerStates: state.player_states,
              isStreaming: false,
              streamingContent: '',
              streamingSpeakerId: null,
              isProcessingReactions: false,
              thinkingTip: '',
            });
          },
          error: (message) => {
            console.warn('Stream error (continuing):', message.message || message);
          },
        },
        controller.signal,
      );
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
      operations.finish(operationKey, controller);
      // Only update state if this controller wasn't aborted (i.e. still the active session)
      if (!controller.signal.aborted && appliesToSession(get, sessionId)) {
        set({ isStreaming: false, streamingContent: '', streamingSpeakerId: null, isProcessingReactions: false, thinkingTip: '' });
      }
    }
  },

  submitVote: async (suspectId: string, suspectName: string, reasoning?: string) => {
    const { sessionId, humanCharacterId } = get();
    if (!sessionId || !humanCharacterId) return;

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
