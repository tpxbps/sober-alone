import axios from 'axios';
import type {
  StartWorkflowResponse,
  WorkflowStateResponse,
  ResumeWorkflowResponse,
  StepInfo,
  AssetProgress,
  CheckpointInfo,
} from '@/types/editor';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

const RAW_API_BASE = API_BASE_URL;

export const editorApi = {
  // Start a new workflow
  startWorkflow: async (params: {
    user_idea: string;
    player_count?: number;
    difficulty?: number;
    num_clue_rounds?: number;
    prompts?: Record<string, string>;
  }): Promise<StartWorkflowResponse> => {
    const response = await api.post('/script-editor/start', params);
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
      game_data_sections?: unknown;
      prompt?: string;
    }
  ): Promise<ResumeWorkflowResponse> => {
    const response = await api.post(`/script-editor/${threadId}/resume`, data);
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

  // Retry a failed convert task
  retryConvert: async (threadId: string, taskId: string): Promise<{ success: boolean; message: string; task_status?: string }> => {
    const response = await api.post(`/script-editor/${threadId}/retry-convert/${taskId}`);
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
  ): (() => void) => {
    const url = `${RAW_API_BASE}/script-editor/${threadId}/progress-stream`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed.type === 'convert_progress' && parsed.data) {
          onConvertProgress(parsed.data);
        } else if (parsed.type === 'asset_progress' && parsed.data) {
          onAssetProgress(parsed.data);
        } else if (parsed.type === 'done') {
          onDone();
          eventSource.close();
        }
      } catch {
        // ignore malformed
      }
    };

    eventSource.onerror = () => {
      // Reconnection is handled automatically by EventSource,
      // but if the stream is truly done we close it
      if (eventSource.readyState === EventSource.CLOSED) {
        onDone();
      }
    };

    return () => eventSource.close();
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
        headers: { 'Content-Type': 'application/json' },
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
