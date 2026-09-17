import { editorApi } from './editorApi';
import type { EditorOperationResponse } from '@/types/editor';

export class ObservationCancelled extends Error {}

type Callbacks = {
  snapshot: (result: EditorOperationResponse) => void;
  convert: Parameters<typeof editorApi.openProgressStream>[1];
  assets: Parameters<typeof editorApi.openProgressStream>[2];
  safety: Parameters<typeof editorApi.openProgressStream>[4];
  outline: Parameters<typeof editorApi.openProgressStream>[5];
  workflow: Parameters<typeof editorApi.openProgressStream>[6];
};

/** A healthy stream has no polling; disconnected operations use bounded backoff. */
export function observeEditorOperation(thread: string, operation: string, callbacks: Callbacks) {
  let closed = false;
  let healthy = false;
  let terminal = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let closeStream: (() => void) | undefined;
  let checking: Promise<void> | undefined;
  let resolve!: (value: EditorOperationResponse) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<EditorOperationResponse>((yes, no) => { resolve = yes; reject = no; });
  const cleanup = () => { closed = true; clearTimeout(timer); closeStream?.(); };
  const schedule = () => {
    if (closed || healthy) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      void check();
      if (!terminal) connect();
    }, [5000, 10000, 20000, 30000][Math.min(attempt++, 3)]);
  };
  const check = (): Promise<void> => {
    if (closed) return Promise.resolve();
    if (checking) return checking;
    checking = (async () => {
      try {
        const result = await editorApi.getOperation(thread, operation);
        if (closed) return;
        callbacks.snapshot(result);
        if (['complete', 'paused', 'failed'].includes(result.operation_status)) {
          cleanup();
          resolve(result);
        }
      } catch (error) {
        const status = (error as { response?: { status?: number } }).response?.status;
        if (status && [401, 403, 404].includes(status)) { cleanup(); reject(error); }
      } finally {
        checking = undefined;
        if (!closed && !healthy) schedule();
      }
    })();
    return checking;
  };
  const connect = () => {
    if (closed) return;
    closeStream?.();
    closeStream = editorApi.openProgressStream(thread, callbacks.convert, callbacks.assets,
      reason => {
        healthy = false;
        if (reason === 'unauthorized') { cleanup(); reject(new Error('页面授权已失效，请刷新后重试')); return; }
        if (reason === 'complete') { terminal = true; void check(); }
        else schedule();
      }, callbacks.safety, callbacks.outline, event => {
        callbacks.workflow?.(event);
        if (event.operation_id === operation && event.finished) {
          terminal = true;
          healthy = false;
          void check();
        }
      }, () => { healthy = true; attempt = 0; clearTimeout(timer); }, operation);
  };
  connect();
  void check();
  return { promise, close: () => { if (!closed) { cleanup(); reject(new ObservationCancelled()); } } };
}
