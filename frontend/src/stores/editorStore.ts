import { create } from 'zustand';
import { editorApi } from '@/lib/editorApi';
import type { EditorInterruptInfo, EditorWorkflowState, AssetProgress, CheckpointInfo, EditorOperationResponse, StartWorkflowResponse, ResumeWorkflowResponse } from '@/types/editor';

const EDITOR_SESSION_KEY = 'editorSession';

// Interrupt steps that require user review
const REVIEW_STEPS = new Set([
  'review_outline',
  'review_first_draft',
  'review_final',
  'review_report',
  'review_quality',
  'review_game_data',
  'safety_check',
  'review_asset_plan',
]);

// Generation steps that map to the interrupt step that follows them
const GEN_TO_REVIEW_STEP: Record<string, string> = {
  generate_outline: 'review_outline',
  generate_first_draft: 'review_first_draft',
  review_by_llm: 'review_report',
  check_game_quality: 'review_quality',
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
    review_final: '终稿确认',
    review_report: '审稿意见确认',
    review_quality: '质量检查结果',
    review_game_data: '游戏数据确认',
    safety_check: '安全审查',
    review_asset_plan: '资源更新确认',
  };

  const prompts = state.prompts || {};
  const info: EditorInterruptInfo = {
    step,
    step_label: STEP_LABELS[step] || step,
    generated_content: '',
    characters: (state.characters || []) as EditorInterruptInfo['characters'],
    character_scripts: state.character_scripts || {},
    review_opinion: state.review_opinion || '',
    human_review: state.human_review || '',
    first_draft: state.first_draft || '',
    quality_report: state.quality_report,
    game_data_sections: state.game_data_sections || {},
    prompt_used: '',
    rejected: step === 'safety_check' && !state.safety_passed,
    workflow_mode: state.workflow_mode,
  };

  if (step === 'review_outline') {
    info.generated_content = state.outline || '';
    info.prompt_used = prompts.generate_outline || '';
  } else if (step === 'review_first_draft') {
    info.generated_content = state.first_draft || '';
    info.prompt_used = prompts.generate_first_draft || '';
  } else if (step === 'review_report') {
    info.generated_content = state.review_opinion || '';
    info.prompt_used = prompts.review || '';
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
  operationId?: string;
  targetStep?: string;
  currentStep?: string;
  pendingKind?: 'start' | 'edit' | 'resume';
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

export function hasStoredEditorSession(): boolean {
  return Boolean(loadSession()?.threadId);
}

class OperationPollCancelled extends Error {}

let _operationPollEpoch = 0;
const OPERATION_POLL_INTERVAL_MS = 5000;

function operationErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object' || !('response' in error)) return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
}

function isFatalRestoreError(error: unknown): boolean {
  const status = operationErrorStatus(error);
  return status === 401 || status === 403 || status === 404;
}

async function pollDelay(epoch: number): Promise<void> {
  // Long-running LLM work continues independently on the backend. A slower
  // status poll keeps database traffic bounded without delaying the operation.
  await new Promise((resolve) => window.setTimeout(resolve, OPERATION_POLL_INTERVAL_MS));
  if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
}

async function waitForOperation(
  threadId: string,
  operationId: string,
  epoch: number,
  onPending?: () => Promise<void>,
): Promise<EditorOperationResponse & (StartWorkflowResponse | ResumeWorkflowResponse)> {
  for (;;) {
    if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
    let result: EditorOperationResponse;
    try {
      result = await editorApi.getOperation(threadId, operationId);
    } catch (error) {
      if (isFatalRestoreError(error)) throw error;
      await pollDelay(epoch);
      continue;
    }
    if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
    if (result.operation_status === 'failed') {
      throw new Error(result.error_message || '后台操作失败');
    }
    if ((result.operation_status === 'complete' || result.operation_status === 'paused') && result.state && result.current_step) {
      return result as EditorOperationResponse & (StartWorkflowResponse | ResumeWorkflowResponse);
    }
    await onPending?.();
    await pollDelay(epoch);
  }
}

function hasIncompleteTasks(progress: AssetProgress | null): boolean {
  return Boolean(
    progress?.phases?.some((phase) =>
      phase.tasks?.some((task) => !['complete', 'skipped'].includes(task.status)),
    ),
  );
}

function needsDetailedProgress(step: string | undefined): boolean {
  return [
    'convert_to_game_data',
    'safety_check',
    'save_to_database',
    'generate_assets',
  ].includes(step || '');
}

async function loadProgressSnapshots(threadId: string): Promise<{
  convertProgress: AssetProgress | null;
  assetProgress: AssetProgress | null;
}> {
  const [convertResult, assetResult] = await Promise.allSettled([
    editorApi.getConvertProgress(threadId),
    editorApi.getAssetProgress(threadId),
  ]);
  return {
    convertProgress:
      convertResult.status === 'fulfilled' ? convertResult.value.progress : null,
    assetProgress:
      assetResult.status === 'fulfilled' ? assetResult.value.progress : null,
  };
}

async function waitForWorkflowState(threadId: string, epoch: number) {
  for (;;) {
    if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
    try {
      return await editorApi.getState(threadId);
    } catch (error) {
      if (isFatalRestoreError(error)) throw error;
      await pollDelay(epoch);
    }
  }
}

interface EditorState {
  // Workflow state
  threadId: string | null;
  scriptId: string | null;
  scriptTitle: string;
  currentStep: string;
  workflowMode: 'create' | 'edit';
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
    ending_mode?: "single" | "multiple";
  }) => Promise<void>;
  startEditWorkflow: (scriptId: string) => Promise<void>;
  resumeWorkflow: (action: string, content?: string, prompt?: string, gameDataSections?: unknown, humanReview?: string, selectedAssetIds?: string[], qualityReportId?: string) => Promise<void>;
  fetchState: () => Promise<void>;
  restoreSession: () => Promise<boolean>;
  openProgressStream: () => void;
  closeProgressStream: () => void;
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
  workflowMode: 'create',
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
    const pollEpoch = ++_operationPollEpoch;
    set({ isStarting: true, error: null, workflowState: null, interruptInfo: null, currentStep: "generate_outline" });
    try {
      const accepted = await editorApi.startWorkflow(params);

      saveSession({
        threadId: accepted.thread_id,
        operationId: accepted.operation_id,
        targetStep: accepted.target_step,
        currentStep: accepted.target_step,
        pendingKind: 'start',
      });
      set({ threadId: accepted.thread_id, currentStep: accepted.target_step });
      const result = await waitForOperation(accepted.thread_id, accepted.operation_id, pollEpoch);
      saveSession({ threadId: result.thread_id, currentStep: result.current_step });

      set({
        threadId: result.thread_id,
        scriptId: result.script_id,
        scriptTitle: result.script_title,
        currentStep: result.current_step,
        workflowMode: result.state.workflow_mode || 'create',
        isComplete: false,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        isStarting: false,
      });
    } catch (err: unknown) {
      if (err instanceof OperationPollCancelled) return;
      const message = err instanceof Error ? err.message : '启动失败';
      set({ error: message, isStarting: false });
    }
  },

  startEditWorkflow: async (scriptId) => {
    const pollEpoch = ++_operationPollEpoch;
    set({ isStarting: true, error: null });
    try {
      const accepted = await editorApi.startEditWorkflow(scriptId);
      saveSession({
        threadId: accepted.thread_id,
        operationId: accepted.operation_id,
        targetStep: accepted.target_step,
        currentStep: accepted.target_step,
        pendingKind: 'edit',
      });
      set({ threadId: accepted.thread_id, currentStep: accepted.target_step });
      const result = await waitForOperation(accepted.thread_id, accepted.operation_id, pollEpoch);
      saveSession({ threadId: result.thread_id, currentStep: result.current_step });
      set({
        threadId: result.thread_id,
        scriptId: result.script_id,
        scriptTitle: result.script_title,
        currentStep: result.current_step,
        workflowMode: 'edit',
        isComplete: false,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        isStarting: false,
      });
    } catch (err: unknown) {
      if (err instanceof OperationPollCancelled) return;
      const message = err instanceof Error ? err.message : '打开编辑失败';
      set({ error: message, isStarting: false });
    }
  },

  resumeWorkflow: async (action, content, prompt, gameDataSections, humanReview, selectedAssetIds, qualityReportId) => {
    const { threadId, currentStep, workflowMode } = get();
    if (!threadId) return;
    const pollEpoch = ++_operationPollEpoch;

    // Optimistic: on confirm, immediately advance timeline to next generation step
    const optimisticStep = workflowMode === 'edit' && currentStep === 'review_game_data'
      ? currentStep
      : action === "confirm" && currentStep
      ? (OPTIMISTIC_STEP_MAP[currentStep] || currentStep)
      : currentStep;

    // Pre-open SSE stream for progress-heavy steps (BEFORE POST, so events aren't missed)
    const needsSSE = optimisticStep === "convert_to_game_data"
      || optimisticStep === "check_game_quality"
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
      const accepted = await editorApi.resume(threadId, {
        action,
        content,
        prompt,
        game_data_sections: gameDataSections,
        human_review: humanReview,
        selected_asset_ids: selectedAssetIds,
        quality_report_id: qualityReportId,
      });
      saveSession({
        threadId,
        operationId: accepted.operation_id,
        targetStep: accepted.target_step,
        currentStep: optimisticStep,
        pendingKind: 'resume',
      });
      const result = await waitForOperation(threadId, accepted.operation_id, pollEpoch);
      saveSession({ threadId, currentStep: result.current_step });

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
      if (err instanceof OperationPollCancelled) return;
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
    const pollEpoch = ++_operationPollEpoch;

    const pendingStart = session.pendingKind === 'start' || session.pendingKind === 'edit';
    set({
      threadId: session.threadId,
      currentStep: session.targetStep || session.currentStep || '',
      isStarting: Boolean(session.operationId && pendingStart),
      isLoading: Boolean(session.operationId && !pendingStart) || !session.operationId,
      error: null,
    });

    try {
      const refreshProgress = async () => {
        if (!needsDetailedProgress(session.currentStep || session.targetStep)) {
          return { convertProgress: null, assetProgress: null };
        }
        const progress = await loadProgressSnapshots(session.threadId);
        set(progress);
        return progress;
      };

      if (session.operationId) {
        await refreshProgress();
        const pending = await waitForOperation(
          session.threadId,
          session.operationId,
          pollEpoch,
          async () => {
            await refreshProgress();
          },
        );
        const progress = await refreshProgress();
        const convertIncomplete = hasIncompleteTasks(progress.convertProgress);
        const assetIncomplete = hasIncompleteTasks(progress.assetProgress);
        const restoredComplete =
          pending.is_complete && !convertIncomplete && !assetIncomplete;
        saveSession({ threadId: session.threadId, currentStep: pending.current_step });
        if (restoredComplete) clearSession();
        set({
          currentStep: convertIncomplete
            ? 'convert_to_game_data'
            : assetIncomplete
              ? 'generate_assets'
              : pending.current_step,
          isComplete: restoredComplete,
          workflowState: pending.state,
          interruptInfo: convertIncomplete || assetIncomplete ? null : pending.interrupt,
          scriptId: pending.state?.script_id || null,
          scriptTitle: pending.state?.script_title || '',
          workflowMode: pending.state?.workflow_mode || 'create',
          convertProgress: progress.convertProgress,
          assetProgress: progress.assetProgress,
          isLoading: false,
          isStarting: false,
        });
        return !restoredComplete;
      }
      const result = await waitForWorkflowState(session.threadId, pollEpoch);
      const progress = await refreshProgress();
      const convertIncomplete = hasIncompleteTasks(progress.convertProgress);
      const assetIncomplete = hasIncompleteTasks(progress.assetProgress);
      const restoredComplete = result.is_complete && !convertIncomplete && !assetIncomplete;
      if (restoredComplete) clearSession();

      // Use backend interrupt info, or reconstruct from state if missing
      const interruptInfo = result.interrupt || reconstructInterruptInfo(
        result.current_step,
        result.state,
      );

      set({
        currentStep: convertIncomplete
          ? 'convert_to_game_data'
          : assetIncomplete
            ? 'generate_assets'
            : interruptInfo?.step || result.current_step,
        workflowMode: result.state.workflow_mode || 'create',
        isComplete: restoredComplete,
        workflowState: result.state,
        interruptInfo: convertIncomplete || assetIncomplete ? null : interruptInfo,
        scriptTitle: result.state?.script_title || '',
        scriptId: result.state?.script_id || null,
        convertProgress: progress.convertProgress,
        assetProgress: progress.assetProgress,
        isLoading: false,
        isStarting: false,
      });
      return !restoredComplete;
    } catch (error) {
      if (error instanceof OperationPollCancelled) return false;
      if (isFatalRestoreError(error)) {
        clearSession();
        set({ threadId: null, isLoading: false, isStarting: false });
      } else {
        set({
          error: error instanceof Error ? error.message : '工作流恢复失败',
          isLoading: false,
          isStarting: false,
        });
      }
      return false;
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
    _operationPollEpoch += 1;
    clearSession();
    set({
      threadId: null,
      scriptId: null,
      scriptTitle: '',
      currentStep: '',
      workflowMode: 'create',
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
      const convertIncomplete = cp?.phases?.some((p) => p.tasks?.some((t) => !["complete", "skipped"].includes(t.status)));
      const assetIncomplete = ap?.phases?.some((p) => p.tasks?.some((t) => !["complete", "skipped"].includes(t.status)));
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
  review_report: "generate_final_draft",
  review_final: "convert_to_game_data",
  review_game_data: "check_game_quality",
  safety_check: "generate_assets",
  review_asset_plan: "generate_assets",
};
