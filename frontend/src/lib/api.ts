import axios from 'axios';
import type {
  Script,
  Character,
  CreateGameRequest,
  CreateGameResponse,
  GameStateResponse,
  GameRecord,
  StageTransition,
  VoteResults,
  StreamingMessage,
  LLMConfig,
} from '@/types/game';
import type { SystemCapabilities } from '@/types/capabilities';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const systemApi = {
  getCapabilities: async (): Promise<SystemCapabilities> => {
    const response = await api.get('/system/capabilities');
    return response.data;
  },
};

// ============ Script APIs ============
export const scriptApi = {
  // List all available scripts
  listScripts: async (): Promise<{ success: boolean; scripts: Script[] }> => {
    const response = await api.get('/game/scripts');
    return response.data;
  },

  // Get script characters
  getScriptCharacters: async (scriptId: string): Promise<{ success: boolean; characters: Character[] }> => {
    const response = await api.get(`/game/scripts/${scriptId}/characters`);
    return response.data;
  },
};

// ============ Game APIs ============
export const gameApi = {
  // Create new game session
  createGame: async (request: CreateGameRequest): Promise<CreateGameResponse> => {
    // Convert ai_models to llm_configs format for backend
    const llmConfigs: Record<string, LLMConfig> | undefined = request.ai_models
      ? Object.fromEntries(
          Object.entries(request.ai_models).map(([charId, modelId]) => {
            const providerByModel: Record<string, string> = {
              'deepseek-v4-flash': 'deepseek',
              'step-3.5-flash': 'stepfun',
              'qwen3.5-flash-2026-02-23': 'alibaba',
              'doubao-seed-2-0-mini-260215': 'bytedance',
            };
            return [
              charId,
              { provider: providerByModel[modelId] || 'deepseek', model: modelId },
            ];
          })
        )
      : undefined;

    const response = await api.post('/game/create', {
      script_id: request.script_id,
      human_character_id: request.human_character_id,
      llm_configs: llmConfigs,
    });
    return response.data;
  },

  // Get game state
  getGameState: async (sessionId: string): Promise<GameStateResponse> => {
    const response = await api.get(`/game/${sessionId}/state`);
    return response.data;
  },

  // Advance to next stage
  advanceStage: async (sessionId: string): Promise<{ success: boolean; transition: StageTransition }> => {
    const response = await api.post(`/game/${sessionId}/advance`);
    return response.data;
  },

  // Get game history/records
  getGameHistory: async (sessionId: string, limit?: number): Promise<{
    success: boolean;
    records: GameRecord[];
    count: number;
  }> => {
    const params = limit ? { limit } : {};
    const response = await api.get(`/game/${sessionId}/records`, { params });
    return response.data;
  },

  // End game
  endGame: async (sessionId: string): Promise<{ success: boolean; message: string }> => {
    const response = await api.post(`/game/${sessionId}/end`);
    return response.data;
  },

  // Abandon game session (for mid-game exit)
  abandonSession: async (sessionId: string): Promise<{ success: boolean; message: string }> => {
    const response = await api.post(`/game/${sessionId}/abandon`);
    return response.data;
  },
};

// ============ Speech APIs ============
export const speechApi = {
  // Human player speech (SSE streaming)
  humanSpeakStream: async (sessionId: string, content: string, signal?: AbortSignal): Promise<Response> => {
    const response = await fetch(
      `${API_BASE_URL}/game/${sessionId}/speech`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
        signal,
      }
    );
    return response;
  },

  // AI speech stream (SSE)
  aiSpeakStream: async (sessionId: string, characterId: string, signal?: AbortSignal): Promise<Response> => {
    const response = await fetch(
      `${API_BASE_URL}/game/${sessionId}/ai-speech/${characterId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal,
      }
    );
    return response;
  },

  // Process SSE stream
  processSSEStream: async function* (
    response: Response,
    signal?: AbortSignal
  ): AsyncGenerator<StreamingMessage> {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Response body is not readable');

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            yield data;
          } catch {
            // Skip invalid JSON
          }
        }
      }
    }
  },
};

// ============ Vote APIs ============
export const voteApi = {
  // Submit human vote
  submitVote: async (
    sessionId: string,
    suspectId: string,
    suspectName: string,
    reasoning?: string
  ): Promise<{ success: boolean; message: string }> => {
    const response = await api.post(`/game/${sessionId}/vote`, {
      suspect_id: suspectId,
      suspect_name: suspectName,
      reasoning: reasoning || '',
    });
    return response.data;
  },

  // Finalize voting and advance to review
  finalizeVoting: async (sessionId: string): Promise<{
    success: boolean;
    vote_results: VoteResults;
    review_message: string;
    transition: StageTransition;
  }> => {
    const response = await api.post(`/game/${sessionId}/finalize-voting`, {}, {
      timeout: 180000, // 3 minutes — AI agents vote in parallel, each may take ~30s
    });
    return response.data;
  },
};

export default api;
