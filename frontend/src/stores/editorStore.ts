import { create } from 'zustand';
import { editorApi } from '@/lib/editorApi';
import type { EditorInterruptInfo, EditorWorkflowState, AssetProgress, CheckpointInfo } from '@/types/editor';

const EDITOR_SESSION_KEY = 'editorSession';

// Interrupt steps that require user review
const REVIEW_STEPS = new Set([
  'review_outline',
  'review_first_draft',
  'review_final',
  'review_game_data',
  'safety_check',
]);

// Generation steps that map to the interrupt step that follows them
const GEN_TO_REVIEW_STEP: Record<string, string> = {
  generate_outline: 'review_outline',
  generate_first_draft: 'review_first_draft',
  review_by_llm: 'review_final',     // after LLM review, generate_final_draft runs, then review_final
  generate_final_draft: 'review_final',
  convert_to_game_data: 'review_game_data',
};

/**
 * Reconstruct interruptInfo from state data when backend doesn't return it.
 * Uses current_step and workflowState to determine what review stage the user should see.
 */
function reconstructInterruptInfo(
  currentStep: string,
  state: EditorWorkflowState | null,
): EditorInterruptInfo | null {
  if (!state) return null;

  // Determine the review step from the current generation step
  let step = currentStep;
  if (!REVIEW_STEPS.has(step)) {
    step = GEN_TO_REVIEW_STEP[step] || '';
  }
  if (!step) return null;

  const STEP_LABELS: Record<string, string> = {
    review_outline: '大纲审阅',
    review_first_draft: '初稿审阅',
    review_final: '审稿修订',
    review_game_data: '游戏数据确认',
    safety_check: '安全审查',
  };

  const prompts = state.prompts || {};
  const info: EditorInterruptInfo = {
    step,
    step_label: STEP_LABELS[step] || step,
    generated_content: '',
    characters: (state.characters || []) as EditorInterruptInfo['characters'],
    character_scripts: state.character_scripts || {},
    review_opinion: state.review_opinion || '',
    game_data_sections: state.game_data_sections || {},
    prompt_used: '',
    rejected: step === 'safety_check' && !state.safety_passed,
  };

  if (step === 'review_outline') {
    info.generated_content = state.outline || '';
    info.prompt_used = prompts.generate_outline || '';
  } else if (step === 'review_first_draft') {
    info.generated_content = state.first_draft || '';
    info.prompt_used = prompts.generate_first_draft || '';
  } else if (step === 'review_final') {
    info.generated_content = state.final_draft || '';
    info.prompt_used = prompts.generate_final_draft || '';
  } else if (step === 'review_game_data') {
    info.prompt_used = prompts.convert_to_game_data || '';
  }

  return info;
}

interface EditorSession {
  threadId: string;
}

function loadSession(): EditorSession | null {
  try {
    const raw = localStorage.getItem(EDITOR_SESSION_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

function saveSession(session: EditorSession) {
  localStorage.setItem(EDITOR_SESSION_KEY, JSON.stringify(session));
}

function clearSession() {
  localStorage.removeItem(EDITOR_SESSION_KEY);
}

interface EditorState {
  // Workflow state
  threadId: string | null;
  scriptId: string | null;
  scriptTitle: string;
  currentStep: string;
  isComplete: boolean;

  // Data
  workflowState: EditorWorkflowState | null;
  interruptInfo: EditorInterruptInfo | null;

  // UI state
  isLoading: boolean;
  isStarting: boolean;
  error: string | null;

  // Asset progress
  assetProgress: AssetProgress | null;

  // Convert progress
  convertProgress: AssetProgress | null;

  // Backtracking / time-travel
  viewingCheckpoint: CheckpointInfo | null;
  history: CheckpointInfo[];

  // Actions
  startWorkflow: (params: {
    user_idea: string;
    player_count?: number;
    difficulty?: number;
    num_clue_rounds?: number;
  }) => Promise<void>;
  resumeWorkflow: (action: string, content?: string, prompt?: string, gameDataSections?: unknown, humanReview?: string) => Promise<void>;
  fetchState: () => Promise<void>;
  restoreSession: () => Promise<boolean>;
  openProgressStream: () => void;
  closeProgressStream: () => void;
  retryConvert: (taskId: string) => Promise<void>;
  retryAsset: (taskId: string) => Promise<void>;
  updateTitle: (title: string) => Promise<void>;
  reset: () => void;

  // Backtracking actions
  fetchHistory: () => Promise<void>;
  viewCheckpoint: (checkpoint: CheckpointInfo | null) => void;
  forkFromCheckpoint: (checkpointId: string, stateUpdates?: unknown) => Promise<void>;
}

// Module-level SSE close handle
let _sseClose: (() => void) | null = null;

export const useEditorStore = create<EditorState>((set, get) => ({
  threadId: null,
  scriptId: null,
  scriptTitle: '',
  currentStep: '',
  isComplete: false,
  workflowState: null,
  interruptInfo: null,
  isLoading: false,
  isStarting: false,
  error: null,
  assetProgress: null,
  convertProgress: null,
  viewingCheckpoint: null,
  history: [],

  startWorkflow: async (params) => {
    set({ isStarting: true, error: null });
    try {
      const result = await editorApi.startWorkflow(params);

      // Persist session
      if (result.thread_id) {
        saveSession({ threadId: result.thread_id });
      }

      set({
        threadId: result.thread_id,
        scriptId: result.script_id,
        scriptTitle: result.script_title,
        currentStep: result.current_step,
        isComplete: false,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        isStarting: false,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '启动失败';
      set({ error: message, isStarting: false });
    }
  },

  resumeWorkflow: async (action, content, prompt, gameDataSections, humanReview) => {
    const { threadId, currentStep } = get();
    if (!threadId) return;

    // Optimistic: on confirm, immediately advance timeline to next generation step
    const optimisticStep = action === "confirm" && currentStep
      ? (OPTIMISTIC_STEP_MAP[currentStep] || currentStep)
      : currentStep;

    // Pre-open SSE stream for progress-heavy steps (BEFORE POST, so events aren't missed)
    const needsSSE = optimisticStep === "convert_to_game_data"
      || optimisticStep === "safety_check"
      || optimisticStep === "save_to_database"
      || optimisticStep === "generate_assets";
    if (needsSSE) {
      _sseClose?.();
      _sseClose = editorApi.openProgressStream(
        threadId,
        (convertData) => set({ convertProgress: convertData }),
        (assetData) => set({ assetProgress: assetData }),
        () => { _sseClose = null; },
      );
    }

    set({ isLoading: true, error: null, currentStep: optimisticStep });
    try {
      const result = await editorApi.resume(threadId, {
        action,
        content,
        prompt,
        game_data_sections: gameDataSections,
        human_review: humanReview,
      });

      // Clear session on completion
      if (result.is_complete) {
        clearSession();
      }

      // Close simple SSE, but re-open with completion handling if there are failures
      _sseClose?.();
      _sseClose = null;

      // Check if convert/asset progress has incomplete tasks — keep SSE open for retries
      const { convertProgress: cp, assetProgress: ap } = get();
      const convertHasIncomplete = cp?.phases?.some((p) => p.tasks?.some((t) => !["complete", "skipped"].includes(t.status)));
      const assetHasIncomplete = ap?.phases?.some((p) => p.tasks?.some((t) => !["complete", "skipped"].includes(t.status)));

      if (convertHasIncomplete || assetHasIncomplete) {
        // Re-open SSE with completion-handling callbacks so retries can trigger state transitions
        get().openProgressStream();
      }

      set({
        currentStep: convertHasIncomplete ? optimisticStep : result.current_step,
        isComplete: assetHasIncomplete ? false : result.is_complete,
        workflowState: result.state,
        interruptInfo: convertHasIncomplete ? null : result.interrupt,
        scriptTitle: result.state?.script_title || get().scriptTitle,
        isLoading: false,
        assetProgress: assetHasIncomplete ? ap : null,
      });

      // Refresh checkpoint history so timeline nodes for new phases are clickable
      get().fetchHistory();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '操作失败';
      set({ error: message, isLoading: false, currentStep });
    }
  },

  fetchState: async () => {
    const { threadId } = get();
    if (!threadId) return;

    try {
      const result = await editorApi.getState(threadId);
      set({
        currentStep: result.current_step,
        isComplete: result.is_complete,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        scriptTitle: result.state?.script_title || get().scriptTitle,
      });
    } catch {
      // State might not exist anymore
    }
  },

  restoreSession: async () => {
    const session = loadSession();
    if (!session) return false;

    set({ threadId: session.threadId });

    try {
      const result = await editorApi.getState(session.threadId);
      if (result.is_complete) {
        clearSession();
        return false;
      }

      // Use backend interrupt info, or reconstruct from state if missing
      const interruptInfo = result.interrupt || reconstructInterruptInfo(
        result.current_step,
        result.state,
      );

      set({
        currentStep: interruptInfo?.step || result.current_step,
        isComplete: result.is_complete,
        workflowState: result.state,
        interruptInfo,
        scriptTitle: result.state?.script_title || '',
        scriptId: result.state?.script_id || null,
      });
      return true;
    } catch {
      clearSession();
      set({ threadId: null });
      return false;
    }
  },

  retryConvert: async (taskId: string) => {
    const { threadId, convertProgress } = get();
    if (!threadId) return;

    // Optimistically set the task to "running" in local state
    if (convertProgress?.phases) {
      const updated = JSON.parse(JSON.stringify(convertProgress));
      for (const phase of updated.phases) {
        for (const task of phase.tasks) {
          if (task.id === taskId) {
            task.status = "running";
          }
        }
      }
      set({ convertProgress: updated });
    }

    try {
      const result = await editorApi.retryConvert(threadId, taskId);
      // Update with actual status from backend
      if (result.task_status && convertProgress?.phases) {
        const updated = JSON.parse(JSON.stringify(get().convertProgress || convertProgress));
        for (const phase of updated.phases) {
          for (const task of phase.tasks) {
            if (task.id === taskId) {
              task.status = result.task_status;
            }
          }
        }
        set({ convertProgress: updated });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '重试失败';
      set({ error: message });
      // Revert optimistic update on error — set back to "failed"
      if (convertProgress?.phases) {
        const reverted = JSON.parse(JSON.stringify(get().convertProgress || convertProgress));
        for (const phase of reverted.phases) {
          for (const task of phase.tasks) {
            if (task.id === taskId && task.status === "running") {
              task.status = "failed";
            }
          }
        }
        set({ convertProgress: reverted });
      }
    }
  },

  retryAsset: async (taskId: string) => {
    const { threadId, assetProgress } = get();
    if (!threadId) return;

    // Optimistically set the task to "running"
    if (assetProgress?.phases) {
      const updated = JSON.parse(JSON.stringify(assetProgress));
      for (const phase of updated.phases) {
        for (const task of phase.tasks) {
          if (task.id === taskId) {
            task.status = "running";
          }
        }
      }
      set({ assetProgress: updated });
    }

    try {
      const result = await editorApi.retryAsset(threadId, taskId);
      // Update with actual status from backend
      if (result.task_status && assetProgress?.phases) {
        const updated = JSON.parse(JSON.stringify(get().assetProgress || assetProgress));
        for (const phase of updated.phases) {
          for (const task of phase.tasks) {
            if (task.id === taskId) {
              task.status = result.task_status;
            }
          }
        }
        set({ assetProgress: updated });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '重试失败';
      set({ error: message });
      // Revert on error
      if (assetProgress?.phases) {
        const reverted = JSON.parse(JSON.stringify(get().assetProgress || assetProgress));
        for (const phase of reverted.phases) {
          for (const task of phase.tasks) {
            if (task.id === taskId && task.status === "running") {
              task.status = "failed";
            }
          }
        }
        set({ assetProgress: reverted });
      }
    }
  },

  updateTitle: async (title: string) => {
    const { threadId } = get();
    if (!threadId) return;
    try {
      await editorApi.updateTitle(threadId, title);
      set({ scriptTitle: title });
    } catch (e) {
      console.error('Failed to update title:', e);
    }
  },

  reset: () => {
    clearSession();
    set({
      threadId: null,
      scriptId: null,
      scriptTitle: '',
      currentStep: '',
      isComplete: false,
      workflowState: null,
      interruptInfo: null,
      isLoading: false,
      isStarting: false,
      error: null,
      assetProgress: null,
      convertProgress: null,
      viewingCheckpoint: null,
      history: [],
    });
    // Close any active SSE connection
    _sseClose?.();
    _sseClose = null;
  },

  openProgressStream: () => {
    const { threadId } = get();
    if (!threadId) return;

    // Close existing connection if any
    _sseClose?.();

    const handleAllComplete = () => {
      const tid = get().threadId;
      if (!tid) return;

      // Don't advance if there are still incomplete tasks in progress data
      const { convertProgress: cp, assetProgress: ap } = get();
      const convertIncomplete = cp?.phases?.some((p) => p.tasks?.some((t) => t.status !== "complete"));
      const assetIncomplete = ap?.phases?.some((p) => p.tasks?.some((t) => t.status !== "complete"));
      if (convertIncomplete || assetIncomplete) return;

      editorApi.getState(tid).then((r) => {
        set({
          isComplete: r.is_complete,
          currentStep: r.current_step,
          interruptInfo: r.interrupt,
          workflowState: r.state,
          isLoading: false,
        });
      }).catch(() => {});
    };

    _sseClose = editorApi.openProgressStream(
      threadId,
      (convertData) => {
        set({ convertProgress: convertData });
        if (convertData?.isComplete) {
          // Convert all done — fetch state to transition to review_game_data
          handleAllComplete();
        }
      },
      (assetData) => {
        set({ assetProgress: assetData });
        if (assetData?.isComplete) {
          // Asset generation all done — fetch full state
          handleAllComplete();
        }
      },
      () => {
        _sseClose = null;
      },
    );
  },

  closeProgressStream: () => {
    _sseClose?.();
    _sseClose = null;
  },

  fetchHistory: async () => {
    const { threadId } = get();
    if (!threadId) return;
    try {
      const result = await editorApi.getHistory(threadId);
      set({ history: result.checkpoints });
    } catch {
      // History might not be available
    }
  },

  viewCheckpoint: (checkpoint: CheckpointInfo | null) => {
    set({ viewingCheckpoint: checkpoint });
  },

  forkFromCheckpoint: async (checkpointId: string, stateUpdates?: unknown) => {
    const { threadId } = get();
    if (!threadId) return;

    set({ isLoading: true, error: null });
    try {
      const result = await editorApi.forkFromCheckpoint(threadId, checkpointId, stateUpdates);

      if (result.is_complete) {
        clearSession();
      }

      // For idea phase (current_step = "init"), the backend returns state without re-running.
      // We need to show the idea form. When user submits, it will go through the normal start flow.
      const isIdeaRestart = result.current_step === "init" && !result.interrupt;

      set({
        currentStep: result.current_step,
        isComplete: result.is_complete,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        scriptTitle: result.state?.script_title || get().scriptTitle,
        isLoading: false,
        viewingCheckpoint: null,
        assetProgress: null,
        // If forking to idea phase, keep the workflow state so the form can be pre-filled
        ...(isIdeaRestart ? {
          // Reset to idea phase — the user will use the normal "start" button
          currentStep: '',
        } : {}),
      });

      // Refresh checkpoint history after fork
      get().fetchHistory();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '回溯失败';
      set({ error: message, isLoading: false, viewingCheckpoint: null });
    }
  },
}));

// === Optimistic step mapping ===
// When user confirms a review step, immediately advance to the next generation step
const OPTIMISTIC_STEP_MAP: Record<string, string> = {
  review_outline: "generate_first_draft",
  review_first_draft: "review_by_llm",
  review_final: "convert_to_game_data",
  review_game_data: "generate_assets",
  safety_check: "generate_assets",
};
