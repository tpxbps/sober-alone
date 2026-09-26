import { create } from 'zustand';
import type {
  GameState,
  PublicClue,
  GameRecord,
  PlayerState,
  Character,
  Script,
  VoteResults,
  GameStage,
  StageTransition,
} from '@/types/game';
import api, { gameApi, speechApi, voteApi } from '@/lib/api';
import { adaptGameState } from '@/lib/gameStateAdapter';
import { speechClues, citedIds } from '@/lib/clueScope';
import { OperationRegistry } from '@/lib/operationRegistry';
import { runSpeechStream } from '@/lib/speechStreamRunner';

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
  retryAISpeech: () => Promise<void>;
  skipAISpeech: () => Promise<void>;

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
    turn_processing?: boolean;
    speech_generation?: GameState['speechGeneration'];
    clue_presentation?: GameState['cluePresentation'];
    clue_asset_preload?: string[];
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
  setPendingHumanSpeech: (speech: string | null, clues?: PublicClue[]) => void;
}

const initialState: GameState = {
  speechGeneration: null,
  speechConnectionError: '',
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
    set({ ...initialState, sessionId, isLoading: true });
    try {
      const state = await gameApi.getGameState(sessionId);
      if (!appliesToSession(get, sessionId)) return false;
      if (!state.success) throw new Error("Game state unavailable");
      const historyResponse = await gameApi.getGameHistory(sessionId);
      if (!appliesToSession(get, sessionId)) return false;
      if (!historyResponse.success) throw new Error("Game history unavailable");
      set({ ...adaptGameState(state), records: historyResponse.records || [] });
      return true;
    } catch (error) {
      console.error('Failed to initialize game:', error);
      return false;
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
    if (get().cluePresentation?.status === 'pending') return null;
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
          showStageTransition: state.clue_presentation?.status !== 'pending',
          stageTransitionMessage: result.transition.message || '',
          currentSpeakerId: state.current_speaker_id || null,
          speechQueue: state.speech_queue || [],
          playerStates: state.player_states || [],
          currentRound: state.current_round,
          votes: state.votes || {},
          voteResults: state.vote_results || null,
          publicClues: state.public_clues || [],
          cluePresentation: state.clue_presentation ?? null,
          clueAssetPreload: state.clue_asset_preload ?? [],
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
    if (get().cluePresentation?.status === 'pending') return;
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

  triggerAISpeak: async (characterId: string, retryGenerationId?: string) => {
    if (get().cluePresentation?.status === 'pending') return;
    const { sessionId } = get();
    if (!sessionId || get().isStreaming) return;
    if (!retryGenerationId && (get().speechGeneration?.status === 'failed' || get().speechConnectionError)) return;

    // Register AbortController for this SSE stream
    const operationKey = `ai-speak-${characterId}`;
    const controller = operations.start(operationKey);

    const started = performance.now();
    let displayed = false;
    let finished = false;
    let rafId: number | null = null;
    set({ speechConnectionError: '', isStreaming: true, streamingContent: '', streamingSpeakerId: characterId, thinkingTip: '', streamingClues: speechClues(get().stage, get().publicClues) });

    try {
      const response = await speechApi.aiSpeakStream(sessionId, characterId, controller.signal, retryGenerationId || get().speechGeneration?.generation_id, Boolean(retryGenerationId));
      const stream = speechApi.processSSEStream(response, controller.signal, 15000);

      let fullContent = '';
      // RAF buffer: batch token updates to at most once per animation frame
      let lastFlushedContent = '';
      const flushContent = () => {
        rafId = null;
        if (fullContent !== lastFlushedContent) {
          lastFlushedContent = fullContent;
          if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId)) return;
          set({ streamingContent: fullContent, thinkingTip: '' });
          const generation = get().speechGeneration;
          if (!displayed && fullContent.trim() && generation) {
            displayed = true;
            void api.post(`/game/${sessionId}/speech/displayed`, {
              generation_id: generation.generation_id, attempt_id: generation.attempt_id,
              elapsed_ms: performance.now() - started,
            }).catch(() => {});
          }
        }
      };

      await runSpeechStream(
        stream,
        {
          speech_status: (message) => {
            if (!operations.isCurrent(operationKey, controller) || !appliesToSession(get, sessionId) || !message.generation) return;
            set({ speechGeneration: message.generation, thinkingTip: message.generation.status === 'retrying' ? '响应超时，正在重试…' : '' });
            if (message.generation.status === 'failed') finished = true;
          },
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
            finished = true;
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
                  clue_refs: citedIds(aiFinalContent, get().streamingClues),
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
                  clue_refs: citedIds(pendingHumanSpeech, get().pendingHumanClues),
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
              speechGeneration: state.speech_generation ?? null,
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
            throw new Error(message.message || '发言未完成，请重试。');
          },
        },
        controller.signal,
      );
      if (!finished) throw new Error('连接暂时中断，请重试。');
      // Clean up any remaining RAF
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    } catch (error: unknown) {
      // Silently ignore abort errors (session was reset/changed)
      if (error instanceof DOMException && error.name === 'AbortError') return;
      set({ speechConnectionError: '连接暂时中断，请重试。', isStreaming: false });
      try {
        const state = await gameApi.getGameState(sessionId);
        const history = await gameApi.getGameHistory(sessionId);
        if (appliesToSession(get, sessionId)) set({ ...adaptGameState(state), records: history.records || get().records });
      } catch { /* Keep recovery controls and the draft available. */ }
      console.error('Failed to trigger AI speak:', error);
    } finally {
      if (rafId !== null) cancelAnimationFrame(rafId);
      operations.finish(operationKey, controller);
      // Only update state if this controller wasn't aborted (i.e. still the active session)
      if (!controller.signal.aborted && appliesToSession(get, sessionId)) {
        set({ isStreaming: false, streamingContent: '', streamingSpeakerId: null, isProcessingReactions: false, thinkingTip: '' });
      }
    }
  },

  retryAISpeech: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    const state = await gameApi.getGameState(sessionId);
    const history = await gameApi.getGameHistory(sessionId);
    if (!appliesToSession(get, sessionId)) return;
    set({ ...adaptGameState(state), records: history.records || get().records });
    const generation = state.speech_generation;
    if (generation?.status === 'failed') {
      await get().triggerAISpeak(generation.character_id, generation.generation_id);
    } else if (generation && ['generating', 'streaming', 'retrying'].includes(generation.status)) {
      throw new Error('旧请求尚在取消，请稍后重试');
    } else {
      set({ speechConnectionError: '' });
    }
  },

  skipAISpeech: async () => {
    const { sessionId, speechGeneration } = get();
    if (!sessionId || !speechGeneration) return;
    const { data } = await api.post(`/game/${sessionId}/speech/skip`, { generation_id: speechGeneration.generation_id });
    const history = await gameApi.getGameHistory(sessionId);
    if (appliesToSession(get, sessionId)) set({ ...adaptGameState(data), records: history.records || get().records, speechConnectionError: '' });
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

  acknowledgeCluePresentation: async (presentationId) => {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    const state = await gameApi.acknowledgeCluePresentation(sessionId, presentationId);
    if (!appliesToSession(get, sessionId)) return;
    if (!state.success) throw new Error('确认失败，请重试');
    set({ ...adaptGameState(state), showStageTransition: false });
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
      ...(data.clue_asset_preload !== undefined ? { clueAssetPreload: data.clue_asset_preload } : {}),
      ...(data.clue_presentation !== undefined ? { cluePresentation: data.clue_presentation } : {}),
      isProcessingReactions: Boolean(data.turn_processing),
      sessionId: data.session_id,
      status: data.status as GameState['status'],
      speechGeneration: data.speech_generation ?? null,
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
    set({ pendingHumanSpeech: speech, pendingHumanClues: speech ? speechClues(get().stage, clues ?? get().publicClues) : [] });
  },
}));
