import type { StreamingMessage } from '@/types/game';

export class SpeechConnectionError extends Error {
  status: number;
  constructor(status: number) { super(`Speech connection returned HTTP ${status}`); this.status = status; }
}

/** Decode complete SSE frames, including CRLF, split UTF-8 and a final unterminated frame. */
export async function* decodeSpeechEvents(response: Response, signal?: AbortSignal, idleTimeoutMs = 30000): AsyncGenerator<StreamingMessage> {
  if (!response.ok) throw new SpeechConnectionError(response.status);
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('Speech connection did not return an event stream');
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Speech response has no body');
  const decoder = new TextDecoder();
  let buffer = '';
  let data: string[] = [];
  const parse = () => {
    const payload = data.join('\n');
    data = [];
    if (!payload) return null;
    const value: unknown = JSON.parse(payload);
    if (!value || typeof value !== 'object' || !('type' in value)) throw new Error('Invalid speech event');
    return value as StreamingMessage;
  };
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    while (!signal?.aborted) {
      // Server heartbeats arrive every 10 seconds even during slow inference.
      // A lost transport restarts only the subscription, never the model turn.
      const watchdog = setTimeout(abort, idleTimeoutMs);
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try { chunk = await reader.read(); } finally { clearTimeout(watchdog); }
      const { done, value } = chunk;
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (done && buffer) buffer += '\n';
      let end: number;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, end).replace(/\r$/, '');
        buffer = buffer.slice(end + 1);
        if (!line) {
          const event = parse();
          if (event) yield event;
        } else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (done) {
        const event = parse();
        if (event) yield event;
        return;
      }
    }
  } finally {
    signal?.removeEventListener('abort', abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
