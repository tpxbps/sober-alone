import { create } from 'zustand';
import { editorApi } from '@/lib/editorApi';
import { observeEditorOperation, ObservationCancelled } from '@/lib/editorProgress';
import { OperationOrder } from '@/lib/operationOrder';
import { applyOutlineDelta, applyOutlineSnapshot } from '@/lib/outlineStream';
import type { OutlineProgress, OutlineDelta } from '@/types/outline';
import type { EditorInterruptInfo, EditorWorkflowState, AssetProgress, CheckpointInfo, EditorOperationResponse, StartWorkflowResponse, ResumeWorkflowResponse, SubmittedDraft, GameDataSections } from '@/types/editor';

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
  if (state.error_message && state.retry_step) {
    return { step: state.retry_step, step_label: '处理失败', generated_content: '', prompt_used: '', failed: true, retry_step: state.retry_step };
  }

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
  submitted?: SubmittedDraft;
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

const OperationPollCancelled = ObservationCancelled;
class OperationFailed extends Error {
  result?: EditorOperationResponse;
  constructor(message: string, result?: EditorOperationResponse) { super(message); this.result = result; }
}

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

let activeObservation: { operation: string; epoch: number; promise: Promise<EditorOperationResponse>; close: () => void } | null = null;

async function waitForOperation(
  threadId: string, operationId: string, epoch: number,
  onPending?: (result: EditorOperationResponse) => Promise<void>,
): Promise<EditorOperationResponse & (StartWorkflowResponse | ResumeWorkflowResponse)> {
  if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
  if (activeObservation?.operation !== operationId || activeObservation.epoch !== epoch) {
    activeObservation?.close();
    const store = useEditorStore;
    const accept = (data: { operation_id?: string }) =>
      epoch === _operationPollEpoch && store.getState().threadId === threadId &&
      store.getState().operationId === operationId && (!data.operation_id || data.operation_id === operationId);
    const order = new OperationOrder();
    const fresh = (key: string, data: { operation_id?: string; seq?: number } | null) => {
      if (!data || !accept(data)) return false;
      return order.accept(key, data.seq);
    };
    const observation = observeEditorOperation(threadId, operationId, {
      snapshot: result => {
        if (!accept(result)) return;
        if (result.outline_progress) store.setState({ outlineProgress: applyOutlineSnapshot(store.getState().outlineProgress, result.outline_progress) });
        if (result.state && fresh('state', result)) store.setState({ workflowState: result.state, checkpointId: result.checkpoint_id });
        if (fresh('convert', result.progress?.convert_progress || null)) store.setState({ convertProgress: result.progress!.convert_progress });
        if (fresh('assets', result.progress?.asset_progress || null)) store.setState({ assetProgress: result.progress!.asset_progress });
        const event = result.progress?.workflow;
        if (event && fresh('workflow', event)) store.setState({ currentStep: event.current_step });
        if (['queued', 'running'].includes(result.operation_status)) void onPending?.(result);
      },
      convert: data => { if (fresh('convert', data)) store.setState({ convertProgress: data }); },
      assets: data => { if (fresh('assets', data)) store.setState({ assetProgress: data }); },
      safety: data => { if (fresh('safety', data)) store.setState({ safetyProgress: data }); },
      outline: (type, data) => {
        if (!accept(data)) return;
        const old = store.getState().outlineProgress;
        if (type === 'outline_delta') {
          const next = applyOutlineDelta(old, data as OutlineDelta);
          if (next.value) store.setState({ outlineProgress: next.value });
          if (next.refresh) void store.getState().fetchState();
        } else store.setState({ outlineProgress: applyOutlineSnapshot(old, data as OutlineProgress) });
      },
      workflow: event => {
        if (fresh('workflow', event) && event.current_step) store.setState({ currentStep: event.current_step });
      },
    });
    activeObservation = { operation: operationId, epoch, ...observation };
  }
  const result = await activeObservation.promise;
  if (epoch !== _operationPollEpoch) throw new OperationPollCancelled();
  if (result.operation_status === 'failed') throw new OperationFailed(result.error_message || '后台操作失败', result);
  return result as EditorOperationResponse & (StartWorkflowResponse | ResumeWorkflowResponse);
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
  safetyProgress?: { completed: number; total: number } | null;
  assetProgress: AssetProgress | null;
}> {
  const [convertResult, assetResult] = await Promise.allSettled([
    editorApi.getConvertProgress(threadId),
    editorApi.getAssetProgress(threadId),
  ]);
  const current = useEditorStore.getState();
  const newer = (previous: AssetProgress | null, incoming: AssetProgress | null) =>
    previous?.operation_id === incoming?.operation_id && (previous?.seq || 0) > (incoming?.seq || 0)
      ? previous : incoming;
  return {
    convertProgress:
      convertResult.status === 'fulfilled' ? newer(current.convertProgress, convertResult.value.progress) : current.convertProgress,
    assetProgress:
      assetResult.status === 'fulfilled' ? newer(current.assetProgress, assetResult.value.progress) : current.assetProgress,
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
  outlineProgress: OutlineProgress | null;
  followOutlineOperation: (operationId: string) => Promise<boolean>;
  checkpointId?: string;
  operationId?: string;
  submitted: SubmittedDraft | null;
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
  safetyProgress?: { completed: number; total: number } | null;

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
  resumeWorkflow: (action: string, content?: string, prompt?: string, gameDataSections?: unknown, humanReview?: string, selectedAssetIds?: string[], qualityReportId?: string, feedback?: string, assetTaskId?: string, conversionTaskId?: string) => Promise<void>;
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


export const useEditorStore = create<EditorState>((set, get) => ({
  outlineProgress: null,
  submitted: null,
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
  safetyProgress: null,
  viewingCheckpoint: null,
  history: [],

  startWorkflow: async (params) => {
    const pollEpoch = ++_operationPollEpoch;
    set({ isStarting: true, outlineProgress: null, error: null, workflowState: null, interruptInfo: null, currentStep: "generate_outline" });
    try {
      const accepted = await editorApi.startWorkflow(params);
      if (pollEpoch !== _operationPollEpoch) return;

      saveSession({
        threadId: accepted.thread_id,
        operationId: accepted.operation_id,
        targetStep: accepted.target_step,
        currentStep: accepted.target_step,
        pendingKind: 'start',
      });
      set({ threadId: accepted.thread_id, currentStep: accepted.target_step, operationId: accepted.operation_id });
      const result = await waitForOperation(accepted.thread_id, accepted.operation_id, pollEpoch);
      saveSession({ threadId: result.thread_id, currentStep: result.current_step });

      set({
        threadId: result.thread_id,
        scriptId: result.script_id,
        scriptTitle: result.script_title,
        checkpointId: result.checkpoint_id,
        currentStep: result.current_step,
        workflowMode: result.state.workflow_mode || 'create',
        isComplete: false,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        isStarting: false, operationId: undefined,
      });
    } catch (err: unknown) {
      if (pollEpoch !== _operationPollEpoch || err instanceof OperationPollCancelled) return;
      const message = err instanceof Error ? err.message : '启动失败';
      if (err instanceof OperationFailed) {
        const failed = err.result;
        const step = failed?.current_step || get().currentStep;
        set({ operationId: undefined, currentStep: step,
          ...(failed?.state ? { workflowState: failed.state, checkpointId: failed.checkpoint_id,
            interruptInfo: failed.interrupt ?? reconstructInterruptInfo(step, failed.state) } : {}) });
        const threadId = get().threadId;
        if (threadId) saveSession({ threadId, currentStep: step });
      }
      set({ error: message, isStarting: false });
    }
  },

  startEditWorkflow: async (scriptId) => {
    const pollEpoch = ++_operationPollEpoch;
    set({ isStarting: true, error: null });
    try {
      const accepted = await editorApi.startEditWorkflow(scriptId);
      if (pollEpoch !== _operationPollEpoch) return;
      saveSession({
        threadId: accepted.thread_id,
        operationId: accepted.operation_id,
        targetStep: accepted.target_step,
        currentStep: accepted.target_step,
        pendingKind: 'edit',
      });
      set({ threadId: accepted.thread_id, currentStep: accepted.target_step, operationId: accepted.operation_id });
      const result = await waitForOperation(accepted.thread_id, accepted.operation_id, pollEpoch);
      saveSession({ threadId: result.thread_id, currentStep: result.current_step });
      set({
        threadId: result.thread_id,
        scriptId: result.script_id,
        scriptTitle: result.script_title,
        checkpointId: result.checkpoint_id,
        currentStep: result.current_step,
        workflowMode: 'edit',
        isComplete: false,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        isStarting: false, operationId: undefined,
      });
    } catch (err: unknown) {
      if (pollEpoch !== _operationPollEpoch || err instanceof OperationPollCancelled) return;
      const message = err instanceof Error ? err.message : '打开编辑失败';
      if (err instanceof OperationFailed) {
        const failed = err.result;
        const step = failed?.current_step || get().currentStep;
        set({ operationId: undefined, currentStep: step,
          ...(failed?.state ? { workflowState: failed.state, checkpointId: failed.checkpoint_id,
            interruptInfo: failed.interrupt ?? reconstructInterruptInfo(step, failed.state) } : {}) });
        const threadId = get().threadId;
        if (threadId) saveSession({ threadId, currentStep: step });
      }
      set({ error: message, isStarting: false });
    }
  },

  resumeWorkflow: async (action, content, prompt, gameDataSections, humanReview, selectedAssetIds, qualityReportId, feedback, assetTaskId, conversionTaskId) => {
    const before = get();
    const { threadId, currentStep } = before;
    if (!threadId || before.isLoading) return;
    const pollEpoch = ++_operationPollEpoch;
    const requestId = crypto.randomUUID();
    const submitted: SubmittedDraft = { step: before.interruptInfo?.step || currentStep, content,
      gameData: gameDataSections as GameDataSections | undefined, humanReview };
    const interruptInfo = before.interruptInfo ? { ...before.interruptInfo,
      ...(content !== undefined ? { generated_content: content } : {}),
      ...(gameDataSections ? { game_data_sections: gameDataSections as GameDataSections } : {}),
    } : null;
    set({ isLoading: true, error: null, submitted, interruptInfo, operationId: requestId });
    const payload = { action, content, prompt, game_data_sections: gameDataSections,
      human_review: humanReview, selected_asset_ids: selectedAssetIds, quality_report_id: qualityReportId,
      feedback, asset_task_id: assetTaskId, conversion_task_id: conversionTaskId, request_id: requestId, expected_checkpoint_id: before.checkpointId };
    try {
      let accepted;
      try { accepted = await editorApi.resume(threadId, payload); }
      catch (error) {
        if (operationErrorStatus(error) !== null) throw error;
        accepted = await editorApi.resume(threadId, payload);
      }
      if (pollEpoch !== _operationPollEpoch || get().threadId !== threadId) return;
      set({ operationId: accepted.operation_id });
      saveSession({ threadId, operationId: accepted.operation_id, targetStep: accepted.target_step,
        currentStep, pendingKind: 'resume', submitted });
      const result = await waitForOperation(threadId, accepted.operation_id, pollEpoch);
      if (get().threadId !== threadId || pollEpoch !== _operationPollEpoch) return;
      const progress = await loadProgressSnapshots(threadId);
      if (get().threadId !== threadId || pollEpoch !== _operationPollEpoch) return;
      set({ currentStep: result.current_step, isComplete: result.is_complete && !hasIncompleteTasks(progress.assetProgress),
        workflowState: result.state, interruptInfo: result.interrupt, checkpointId: result.checkpoint_id,
        scriptId: result.state.script_id, scriptTitle: result.state.script_title || get().scriptTitle,
        isLoading: false, submitted: null, operationId: undefined, ...progress });
      saveSession({ threadId, currentStep: result.current_step });
      if (get().isComplete) clearSession();
      get().closeProgressStream();
      void get().fetchHistory();
    } catch (err: unknown) {
      if (err instanceof OperationPollCancelled) return;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const failed = err instanceof OperationFailed ? err.result : undefined;
      if (pollEpoch !== _operationPollEpoch || get().threadId !== threadId) return;
      const step = failed?.current_step || submitted.step;
      set({ error: detail || (err instanceof Error ? err.message : '操作失败'), isLoading: false,
        ...(failed?.state ? { workflowState: failed.state, checkpointId: failed.checkpoint_id, interruptInfo: failed.interrupt ?? null } : {}),
        currentStep: step, operationId: undefined });
      saveSession({ threadId, currentStep: step, submitted });
      get().closeProgressStream();
    }
  },

  fetchState: async () => {
    const { threadId, operationId } = get();
    const epoch = _operationPollEpoch;
    if (!threadId) return;

    try {
      const result = await editorApi.getState(threadId);
      if (epoch !== _operationPollEpoch || get().threadId !== threadId || get().operationId !== operationId) return;
      set({
        outlineProgress: result.outline_progress ? applyOutlineSnapshot(get().outlineProgress, result.outline_progress) : get().outlineProgress,
        ...(!operationId ? { currentStep: result.current_step, interruptInfo: result.interrupt,
          checkpointId: result.checkpoint_id, isComplete: result.is_complete, workflowState: result.state } : {}),
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
      currentStep: session.currentStep || session.targetStep || '',
      submitted: session.submitted || null, operationId: session.operationId,
      isStarting: Boolean(session.operationId && pendingStart),
      isLoading: Boolean(session.operationId && !pendingStart) || !session.operationId,
      error: null,
    });

    try {
      const refreshProgress = async () => {
        if (pollEpoch !== _operationPollEpoch || get().threadId !== session.threadId) throw new OperationPollCancelled();
        if (!needsDetailedProgress(get().currentStep) && !session.operationId) {
          return { convertProgress: null, assetProgress: null };
        }
        const progress = await loadProgressSnapshots(session.threadId);
        if (pollEpoch !== _operationPollEpoch || get().threadId !== session.threadId) throw new OperationPollCancelled();
        set(progress);
        return progress;
      };

      if (session.operationId) {
        await refreshProgress();
        const pending = await waitForOperation(
          session.threadId,
          session.operationId,
          pollEpoch,
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
          checkpointId: pending.checkpoint_id, submitted: null, operationId: undefined,
          workflowState: pending.state,
          interruptInfo: (convertIncomplete || assetIncomplete) && !pending.state?.error_message ? null : pending.interrupt,
          scriptId: pending.state?.script_id || null,
          scriptTitle: pending.state?.script_title || '',
          workflowMode: pending.state?.workflow_mode || 'create',
          convertProgress: progress.convertProgress,
          assetProgress: progress.assetProgress,
          isLoading: false,
          isStarting: false,
        });
        get().closeProgressStream();
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

      const restoredInterrupt = session.submitted && interruptInfo?.step === session.submitted.step ? {
        ...interruptInfo,
        ...(session.submitted.content !== undefined ? { generated_content: session.submitted.content } : {}),
        ...(session.submitted.gameData ? { game_data_sections: session.submitted.gameData } : {}),
      } : interruptInfo;
      set({
        checkpointId: result.checkpoint_id,
        currentStep: convertIncomplete
          ? 'convert_to_game_data'
          : assetIncomplete
            ? 'generate_assets'
            : interruptInfo?.step || result.current_step,
        workflowMode: result.state.workflow_mode || 'create',
        isComplete: restoredComplete,
        workflowState: result.state,
        interruptInfo: (convertIncomplete || assetIncomplete) && !result.state?.error_message ? null : restoredInterrupt,
        scriptTitle: result.state?.script_title || '',
        scriptId: result.state?.script_id || null,
        convertProgress: progress.convertProgress,
        assetProgress: progress.assetProgress,
        isLoading: false,
        isStarting: false, operationId: undefined,
      });
      return !restoredComplete;
    } catch (error) {
      if (error instanceof OperationPollCancelled) return false;
      if (pollEpoch !== _operationPollEpoch || get().threadId !== session.threadId) return false;
      if (error instanceof OperationFailed) {
        const step = error.result?.current_step || session.submitted?.step || session.currentStep;
        saveSession({ threadId: session.threadId, currentStep: step, submitted: session.submitted });
        set({ operationId: undefined });
        get().closeProgressStream();
        const restored = await get().restoreSession();
        set({ error: error.message });
        return restored;
      }
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
    await get().resumeWorkflow('retry_asset', undefined, undefined, undefined, undefined, undefined, undefined, undefined, taskId);
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
      submitted: null, checkpointId: undefined, operationId: undefined,
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
  safetyProgress: null,
      viewingCheckpoint: null,
      history: [],
    });
    // Close any active SSE connection
    activeObservation?.close();
    activeObservation = null;
    set({ outlineProgress: null });
  },

  // Retained for callers that explicitly open/close the editor panel. The
  // accepted operation owns the single observer; opening a panel starts none.
  openProgressStream: () => {},
  closeProgressStream: () => {
    activeObservation?.close();
    activeObservation = null;
  },

  followOutlineOperation: async operationId => {
    const { threadId } = get();
    if (!threadId) return false;
    const epoch = ++_operationPollEpoch;
    set({ operationId, error: null });
    saveSession({ threadId, operationId, currentStep: get().currentStep });
    try {
      const result = await waitForOperation(threadId, operationId, epoch);
      set({ workflowState: result.state, interruptInfo: result.interrupt,
        checkpointId: result.checkpoint_id, currentStep: result.current_step,
        outlineProgress: result.outline_progress || get().outlineProgress,
        isStarting: false, isLoading: false, operationId: undefined });
      saveSession({ threadId, currentStep: result.current_step });
      return true;
    } catch (error) {
      if (error instanceof OperationPollCancelled) return false;
      set({ error: error instanceof Error ? error.message : '本轮未完成',
        isStarting: false, isLoading: false, operationId: undefined });
      saveSession({ threadId, currentStep: get().currentStep });
      return false;
    }
  },

  fetchHistory: async () => {
    const { threadId } = get();
    if (!threadId) return;
    try {
      const result = await editorApi.getHistory(threadId);
      if (get().threadId !== threadId) return;
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
    if (!threadId || get().isLoading) return;
    const epoch = ++_operationPollEpoch;
    get().closeProgressStream();

    set({ isLoading: true, error: null });
    try {
      const result = await editorApi.forkFromCheckpoint(threadId, checkpointId, stateUpdates);
      if (epoch !== _operationPollEpoch || get().threadId !== threadId) return;

      if (result.is_complete) {
        clearSession();
      }

      // For idea phase (current_step = "init"), the backend returns state without re-running.
      // We need to show the idea form. When user submits, it will go through the normal start flow.
      const isIdeaRestart = result.current_step === "init" && !result.interrupt;

      set({
        checkpointId: result.checkpoint_id,
        currentStep: result.current_step,
        isComplete: result.is_complete,
        workflowState: result.state,
        interruptInfo: result.interrupt,
        scriptTitle: result.state?.script_title || get().scriptTitle,
        isLoading: false,
        viewingCheckpoint: null,
        assetProgress: null,
        convertProgress: null, safetyProgress: null, submitted: null, operationId: undefined,
        // If forking to idea phase, keep the workflow state so the form can be pre-filled
        ...(isIdeaRestart ? {
          // Reset to idea phase — the user will use the normal "start" button
          currentStep: '',
        } : {}),
      });
      if (!result.is_complete) saveSession({ threadId, currentStep: isIdeaRestart ? '' : result.current_step });

      // Refresh checkpoint history after fork
      get().fetchHistory();
    } catch (err: unknown) {
      if (epoch !== _operationPollEpoch || get().threadId !== threadId) return;
      const message = err instanceof Error ? err.message : '回溯失败';
      set({ error: message, isLoading: false, viewingCheckpoint: null });
    }
  },
}));
