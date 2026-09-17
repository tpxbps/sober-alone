import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AssetProgress } from '@/types/editor';
import { editorApi } from '@/lib/editorApi';
import { useEditorStore } from './editorStore';

vi.mock('@/lib/editorApi', () => ({ editorApi: { openProgressStream: vi.fn() } }));

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('localStorage', { removeItem: vi.fn() });
  useEditorStore.getState().reset();
  vi.mocked(editorApi.openProgressStream).mockReset().mockReturnValue(vi.fn());
  useEditorStore.setState({ threadId: 'thread', operationId: 'current-operation' });
});
afterEach(() => {
  useEditorStore.getState().closeProgressStream();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('reconnects after a dropped stream, keeps tasks visible and rejects old operation/sequence events', async () => {
  useEditorStore.getState().openProgressStream();
  const first = vi.mocked(editorApi.openProgressStream).mock.calls[0];
  const progress: AssetProgress = { operation_id: 'current-operation', seq: 3,
    isComplete: false, phases: [{ id: 'image', label: '图片', tech: 'Image', tasks: [{ id: 'cover', label: '封面', status: 'running' }] }] };
  first[2](progress);
  first[3]();
  expect(useEditorStore.getState().assetProgress).toEqual(progress);
  await vi.advanceTimersByTimeAsync(1500);
  expect(editorApi.openProgressStream).toHaveBeenCalledTimes(2);
  const second = vi.mocked(editorApi.openProgressStream).mock.calls[1];
  second[2]({ ...progress, seq: 2, isComplete: true });
  second[2]({ ...progress, operation_id: 'old-operation', seq: 100, isComplete: true });
  expect(useEditorStore.getState().assetProgress?.isComplete).toBe(false);
  // Completion of conversion must not close asset progress.
  second[1]({ ...progress, seq: 4, isComplete: true });
  second[2]({ ...progress, seq: 5, isComplete: true });
  expect(useEditorStore.getState().assetProgress?.seq).toBe(5);
  second[3]();
  useEditorStore.getState().closeProgressStream();
  await vi.advanceTimersByTimeAsync(1500);
  expect(editorApi.openProgressStream).toHaveBeenCalledTimes(2);
});
