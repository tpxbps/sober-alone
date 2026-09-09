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
import type { ModelHealthResponse, SystemCapabilities } from '@/types/capabilities';
import { AUTHOR_KEY_HEADER, getStoredAuthorKey } from '@/lib/authorKey';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

let modelHealthCache: { value: ModelHealthResponse; expiresAt: number } | null = null;
let modelHealthRequest: Promise<ModelHealthResponse> | null = null;
let modelHealthSnapshot: ModelHealthResponse | null = null;
const modelHealthListeners = new Set<(value: ModelHealthResponse) => void>();
export function subscribeModelHealth(listener: (value: ModelHealthResponse) => void) {
  modelHealthListeners.add(listener);
  if (modelHealthSnapshot && (modelHealthRequest || (modelHealthCache && modelHealthCache.expiresAt > Date.now()))) {
    listener(modelHealthSnapshot);
  }
  return () => { modelHealthListeners.delete(listener); };
}
const CAPABILITIES_FRONTEND_TTL_MS = 60 * 1000;
let capabilitiesCache: { value: SystemCapabilities; expiresAt: number } | null = null;
let capabilitiesRequest: Promise<SystemCapabilities> | null = null;

api.interceptors.request.use((config) => {
  const authorKey = getStoredAuthorKey();
  if (authorKey) config.headers.set(AUTHOR_KEY_HEADER, authorKey);
  return config;
});

export const systemApi = {
  getCapabilities: async (): Promise<SystemCapabilities> => {
    if (capabilitiesCache && capabilitiesCache.expiresAt > Date.now()) {
      return capabilitiesCache.value;
    }
    if (!capabilitiesRequest) {
      capabilitiesRequest = api
        .get<SystemCapabilities>('/system/capabilities')
        .then((response) => {
          capabilitiesCache = {
            value: response.data,
            expiresAt: Date.now() + CAPABILITIES_FRONTEND_TTL_MS,
          };
          return response.data;
        })
        .finally(() => {
          capabilitiesRequest = null;
        });
    }
    return capabilitiesRequest;
  },
  getModelHealth: async (forceRefresh = false): Promise<ModelHealthResponse> => {
    // Lobby, detail dialog and manual clicks share the same active run.
    if (modelHealthRequest) return modelHealthRequest;
    if (!forceRefresh && modelHealthCache && modelHealthCache.expiresAt > Date.now()) {
      return modelHealthCache.value;
    }
    const poll = async () => {
      const deadline = Date.now() + 120_000;
      let first = true;
      while (true) {
        const response = first && forceRefresh
          ? await api.post<ModelHealthResponse>('/system/model-health/refresh', undefined, { timeout: 10_000 })
          : await api.get<ModelHealthResponse>('/system/model-health', { timeout: 10_000 });
        first = false;
        const maxAge = Number(response.data?.max_age_seconds);
        const value: ModelHealthResponse = {
          models: Array.isArray(response.data?.models) ? response.data.models : [],
          cached: Boolean(response.data?.cached),
          probing: Boolean(response.data?.probing),
          max_age_seconds: Number.isFinite(maxAge) && maxAge >= 0 ? maxAge : 90,
        };
        modelHealthSnapshot = value;
        modelHealthCache = value.probing ? null : {
          value, expiresAt: Date.now() + value.max_age_seconds * 1000,
        };
        modelHealthListeners.forEach((listener) => listener(value));
        if (!value.probing) return value;
        if (Date.now() >= deadline) throw new Error('Model health polling timed out');
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    };
    modelHealthRequest = poll().finally(() => { modelHealthRequest = null; });
    return modelHealthRequest;
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
            return [
              charId,
              { model: modelId },
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
