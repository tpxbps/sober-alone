import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AssetProgress, EditorOperationResponse } from '@/types/editor';
import { editorApi } from '@/lib/editorApi';
import { useEditorStore } from './editorStore';

vi.mock('@/lib/editorApi', () => ({ editorApi: { openProgressStream: vi.fn(), getOperation: vi.fn(), getState: vi.fn(), startWorkflow: vi.fn(), getConvertProgress: vi.fn(), getAssetProgress: vi.fn() } }));
const pending: EditorOperationResponse = { success: true, thread_id: 'thread', operation_id: 'current', operation_status: 'running', target_step: 'generate_outline' };
beforeEach(() => {
  vi.useFakeTimers();
  const storage = new Map<string, string>();
  vi.stubGlobal('localStorage', { removeItem: vi.fn((key: string) => storage.delete(key)), setItem: vi.fn((key: string, value: string) => storage.set(key, value)), getItem: vi.fn((key: string) => storage.get(key) ?? null) });
  useEditorStore.getState().reset();
  vi.mocked(editorApi.openProgressStream).mockReset().mockReturnValue(vi.fn());
  vi.mocked(editorApi.getOperation).mockReset().mockResolvedValue(pending);
  useEditorStore.setState({ threadId: 'thread', currentStep: 'generate_outline' });
});
afterEach(() => {
  useEditorStore.getState().closeProgressStream();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('uses no periodic reads with a healthy stream, then stops completely at a question', async () => {
  const result = useEditorStore.getState().followOutlineOperation('current');
  const stream = vi.mocked(editorApi.openProgressStream).mock.calls[0];
  stream[7]?.();
  await vi.advanceTimersByTimeAsync(60000);
  expect(editorApi.getOperation).toHaveBeenCalledTimes(1);
  vi.mocked(editorApi.getOperation).mockResolvedValue({ ...pending, operation_status: 'complete', current_step: 'outline_wait' });
  stream[3]('complete');
  await result;
  const count = vi.mocked(editorApi.getOperation).mock.calls.length;
  await vi.advanceTimersByTimeAsync(60000);
  expect(editorApi.getOperation).toHaveBeenCalledTimes(count);
  expect(editorApi.openProgressStream).toHaveBeenCalledTimes(1);
});

it('only polls after disconnect and rejects obsolete task events across reconnects', async () => {
  const result = useEditorStore.getState().followOutlineOperation('current');
  const first = vi.mocked(editorApi.openProgressStream).mock.calls[0];
  first[7]?.();
  const progress: AssetProgress = { operation_id: 'current', seq: 3, isComplete: false,
    phases: [{ id: 'image', label: '图片', tech: 'Image', tasks: [{ id: 'cover', label: '封面', status: 'running' }] }] };
  first[2](progress);
  await vi.advanceTimersByTimeAsync(0);
  first[3]('disconnected');
  await vi.advanceTimersByTimeAsync(5000);
  expect(editorApi.openProgressStream).toHaveBeenCalledTimes(2);
  const second = vi.mocked(editorApi.openProgressStream).mock.calls[1];
  second[7]?.();
  second[2]({ ...progress, seq: 2, isComplete: true });
  second[2]({ ...progress, operation_id: 'old', seq: 100, isComplete: true });
  expect(useEditorStore.getState().assetProgress).toEqual(progress);
  second[1]({ ...progress, seq: 4, isComplete: true });
  second[2]({ ...progress, seq: 5, isComplete: true });
  expect(useEditorStore.getState().assetProgress?.seq).toBe(5);
  const count = vi.mocked(editorApi.getOperation).mock.calls.length;
  await vi.advanceTimersByTimeAsync(60000);
  expect(editorApi.getOperation).toHaveBeenCalledTimes(count);
  useEditorStore.getState().closeProgressStream();
  await result;
});

it('does not reconnect on revoked authorization', async () => {
  const result = useEditorStore.getState().followOutlineOperation('current');
  vi.mocked(editorApi.openProgressStream).mock.calls[0][3]('unauthorized');
  expect(await result).toBe(false);
  await vi.advanceTimersByTimeAsync(60000);
  expect(editorApi.openProgressStream).toHaveBeenCalledTimes(1);
  expect(useEditorStore.getState().error).toContain('授权');
});


it('unlocks a failed start and keeps its checkpoint available for retry', async () => {
  const state = { error_message: '提问生成失败', outline_session: { status: 'error' } } as unknown as NonNullable<EditorOperationResponse['state']>;
  vi.mocked(editorApi.startWorkflow).mockResolvedValue(pending);
  vi.mocked(editorApi.getOperation).mockResolvedValue({ ...pending, operation_status: 'failed', current_step: 'generate_outline', state, checkpoint_id: 'failed-checkpoint', error_message: '提问生成失败' });
  await useEditorStore.getState().startWorkflow({ user_idea: '旅馆案件' });
  const store = useEditorStore.getState();
  expect(store.operationId).toBeUndefined();
  expect(store.isStarting).toBe(false);
  expect(store.checkpointId).toBe('failed-checkpoint');
  expect(store.workflowState).toEqual(state);
  expect(JSON.parse(localStorage.getItem('editorSession')!).operationId).toBeUndefined();
});

it('restores a failed outline command without a submission and stops observing it', async () => {
  const state = { error_message: '提问生成失败', outline_session: { status: 'error' } } as unknown as NonNullable<EditorOperationResponse['state']>;
  localStorage.setItem('editorSession', JSON.stringify({ threadId: 'thread', currentStep: 'generate_outline', operationId: 'current' }));
  vi.mocked(editorApi.getOperation).mockResolvedValue({ ...pending, operation_status: 'failed', current_step: 'generate_outline', state, error_message: '提问生成失败' });
  vi.mocked(editorApi.getState).mockResolvedValue({ success: true, thread_id: 'thread', current_step: 'generate_outline', state, is_complete: false, interrupt: null });
  vi.mocked(editorApi.getConvertProgress).mockResolvedValue({ success: true, progress: null });
  vi.mocked(editorApi.getAssetProgress).mockResolvedValue({ success: true, progress: null });
  expect(await useEditorStore.getState().restoreSession()).toBe(true);
  expect(useEditorStore.getState().operationId).toBeUndefined();
  expect(useEditorStore.getState().isLoading).toBe(false);
  expect(useEditorStore.getState().error).toBe('提问生成失败');
  await vi.advanceTimersByTimeAsync(60000);
  expect(editorApi.getOperation).toHaveBeenCalledTimes(1);
  expect(editorApi.getState).toHaveBeenCalledTimes(1);
});
