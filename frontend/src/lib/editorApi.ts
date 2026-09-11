import axios from 'axios';
import type { OutlineCommand, OutlineDelta, OutlineProgress } from '@/types/outline';
import type {
  WorkflowStateResponse,
  ResumeWorkflowResponse,
  StepInfo,
  AssetProgress,
  CheckpointInfo,
  EditorOperationAccepted,
  EditorOperationResponse,
} from '@/types/editor';
import { AUTHOR_KEY_HEADER, getOrCreateAuthorKey } from '@/lib/authorKey';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

const RAW_API_BASE = API_BASE_URL;

api.interceptors.request.use((config) => {
  config.headers.set(AUTHOR_KEY_HEADER, getOrCreateAuthorKey());
  return config;
});

export const editorApi = {
  outlineAction: async (threadId: string, command: OutlineCommand): Promise<EditorOperationAccepted> => {
    const response = await api.post(`/script-editor/${threadId}/outline/actions`, command);
    return response.data;
  },
  claimLegacyOwnership: async (legacyOwnerUuids: string[]): Promise<{
    success: boolean;
    claimed_count: number;
    matched_count: number;
  }> => {
    const response = await api.post('/script-editor/legacy-ownership/claim', {
      legacy_owner_uuids: legacyOwnerUuids,
    });
    return response.data;
  },

  // Start a new workflow
  startWorkflow: async (params: {
    user_idea: string;
    player_count?: number;
    difficulty?: number;
    num_clue_rounds?: number;
    ending_mode?: "single" | "multiple";
    prompts?: Record<string, string>;
  }): Promise<EditorOperationAccepted> => {
    const response = await api.post('/script-editor/start', params);
    return response.data;
  },

  startEditWorkflow: async (scriptId: string): Promise<EditorOperationAccepted> => {
    const response = await api.post(`/script-editor/scripts/${scriptId}/edit`);
    return response.data;
  },

  // Get current workflow state
  getState: async (threadId: string): Promise<WorkflowStateResponse> => {
    const response = await api.get(`/script-editor/${threadId}/state`);
    return response.data;
  },

  // Resume from interrupt
  resume: async (
    threadId: string,
    data: {
      action: string;
      content?: string;
      characters?: unknown[];
      character_scripts?: Record<string, string>;
      human_review?: string;
      quality_report_id?: string;
      game_data_sections?: unknown;
      prompt?: string;
      selected_asset_ids?: string[];
    }
  ): Promise<EditorOperationAccepted> => {
    const response = await api.post(`/script-editor/${threadId}/resume`, data);
    return response.data;
  },

  getOperation: async (
    threadId: string,
    operationId: string,
  ): Promise<EditorOperationResponse> => {
    const response = await api.get(
      `/script-editor/${threadId}/operations/${operationId}`,
    );
    return response.data;
  },

  // Update a step's prompt
  updatePrompt: async (threadId: string, step: string, prompt: string) => {
    const response = await api.put(`/script-editor/${threadId}/prompt/${step}`, { prompt });
    return response.data;
  },

  // Update script title
  updateTitle: async (threadId: string, scriptTitle: string): Promise<{ success: boolean; script_title: string }> => {
    const response = await api.put(`/script-editor/${threadId}/title`, { script_title: scriptTitle });
    return response.data;
  },

  // Get default prompts
  getDefaultPrompts: async (): Promise<{ success: boolean; prompts: Record<string, string> }> => {
    const response = await api.get('/script-editor/prompts/defaults');
    return response.data;
  },

  // Get steps info
  getStepsInfo: async (): Promise<{ success: boolean; steps: StepInfo[] }> => {
    const response = await api.get('/script-editor/steps/info');
    return response.data;
  },

  // Delete a script
  deleteScript: async (scriptId: string) => {
    const response = await api.delete(`/script-editor/scripts/${scriptId}`);
    return response.data;
  },

  // Get asset generation progress
  getAssetProgress: async (threadId: string): Promise<{ success: boolean; progress: AssetProgress | null }> => {
    const response = await api.get(`/script-editor/${threadId}/asset-progress`);
    return response.data;
  },

  // Retry a failed asset task
  retryAsset: async (threadId: string, taskId: string): Promise<{ success: boolean; message: string; task_status?: string }> => {
    const response = await api.post(`/script-editor/${threadId}/retry-asset/${taskId}`);
    return response.data;
  },

  // Get workflow checkpoint history
  getHistory: async (threadId: string): Promise<{ success: boolean; checkpoints: CheckpointInfo[] }> => {
    const response = await api.get(`/script-editor/${threadId}/history`);
    return response.data;
  },

  // Get specific checkpoint state (read-only)
  getCheckpoint: async (threadId: string, checkpointId: string): Promise<{
    success: boolean;
    checkpoint_id: string;
    current_step: string;
    interrupt: unknown;
    state: unknown;
  }> => {
    const response = await api.get(`/script-editor/${threadId}/checkpoint/${checkpointId}`);
    return response.data;
  },

  // Fork from a checkpoint and re-run
  forkFromCheckpoint: async (threadId: string, checkpointId: string, stateUpdates?: unknown): Promise<ResumeWorkflowResponse> => {
    const response = await api.post(`/script-editor/${threadId}/fork`, {
      checkpoint_id: checkpointId,
      state_updates: stateUpdates || null,
    });
    return response.data;
  },

  // Get convert progress
  getConvertProgress: async (threadId: string): Promise<{ success: boolean; progress: AssetProgress | null }> => {
    const response = await api.get(`/script-editor/${threadId}/convert-progress`);
    return response.data;
  },

  /**
   * Open an SSE connection for real-time progress updates.
   * Returns a close function to tear down the connection.
   */
  openProgressStream: (
    threadId: string,
    onConvertProgress: (data: AssetProgress | null) => void,
    onAssetProgress: (data: AssetProgress | null) => void,
    onDone: () => void,
    onOutline?: (type: string, data: OutlineProgress | OutlineDelta) => void,
  ): (() => void) => {
    const url = `${RAW_API_BASE}/script-editor/${threadId}/progress-stream`;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(url, {
          headers: { [AUTHOR_KEY_HEADER]: getOrCreateAuthorKey() },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';
          for (const event of events) {
            const line = event.split('\n').find((item) => item.startsWith('data: '));
            if (!line) continue;
            const parsed = JSON.parse(line.slice(6));
            if (parsed.type?.startsWith('outline_')) onOutline?.(parsed.type, parsed.data);
            else if (parsed.type === 'convert_progress') onConvertProgress(parsed.data ?? null);
            else if (parsed.type === 'asset_progress') onAssetProgress(parsed.data ?? null);
            else if (parsed.type === 'done') {
              onDone();
              controller.abort();
            }
          }
        }
        if (!controller.signal.aborted) onDone();
      } catch (error) {
        if (!(error instanceof DOMException && error.name === 'AbortError')) onDone();
      }
    })();
    return () => controller.abort();
  },

  // Stream chat with AI assistant (SSE)
  streamChat: async (
    params: {
      message: string;
      model: string;
      chat_session_id: string;
      workflow_thread_id?: string;
    },
    signal: AbortSignal,
    onToken: (token: string) => void,
    onDone: () => void,
    onError: (error: string) => void,
    onThinking: (tip: string) => void,
  ) => {
    try {
      const response = await fetch(`${RAW_API_BASE}/script-editor/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          [AUTHOR_KEY_HEADER]: getOrCreateAuthorKey(),
        },
        body: JSON.stringify(params),
        signal,
      });

      if (!response.ok || !response.body) {
        onError(`HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (!data) continue;
            try {
              const parsed = JSON.parse(data);
              if (parsed.type === 'token' && parsed.content) {
                onToken(parsed.content);
              } else if (parsed.type === 'thinking' && parsed.message) {
                onThinking(parsed.message);
              } else if (parsed.type === 'done') {
                onDone();
              } else if (parsed.type === 'error') {
                onError(parsed.message || 'Unknown error');
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
      onDone();
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      onError(err instanceof Error ? err.message : 'Stream failed');
    }
  },
};
