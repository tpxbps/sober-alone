import { describe, expect, it } from 'vitest';
import { decodeSpeechEvents } from './sse';

function response(chunks: Uint8Array[]) {
  return new Response(new ReadableStream({ start(controller) {
    chunks.forEach(chunk => controller.enqueue(chunk)); controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}

describe('speech SSE framing', () => {
  it('preserves every split of Chinese UTF-8, CRLF, multiline data and trailing data', async () => {
    const bytes = new TextEncoder().encode(': ping\r\ndata: {"type":"token",\r\ndata: "text":"你好"}\r\n\r\ndata:{"type":"done"}');
    for (let split = 1; split < bytes.length; split++) {
      const events = [];
      for await (const event of decodeSpeechEvents(response([bytes.slice(0, split), bytes.slice(split)]))) events.push(event);
      expect(events).toEqual([{ type: 'token', text: '你好' }, { type: 'done' }]);
    }
  });
  it('rejects HTTP errors and non-SSE responses instead of silently accepting EOF', async () => {
    for (const res of [new Response('no', { status: 500 }), new Response('<html>proxy</html>')]) {
      await expect(decodeSpeechEvents(res).next()).rejects.toThrow();
    }
  });
  it('ends a subscription whose transport stops delivering heartbeats', async () => {
    let cancelled = false;
    const stalled = new Response(new ReadableStream({ cancel() { cancelled = true; } }),
      { headers: { 'content-type': 'text/event-stream' } });
    expect(await decodeSpeechEvents(stalled, undefined, 10).next()).toEqual({ done: true, value: undefined });
    expect(cancelled).toBe(true);
  });
});
