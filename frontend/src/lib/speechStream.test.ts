import { afterEach, expect, it, vi } from 'vitest'
import { speechApi } from './api'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('closes the transport after 15 seconds without an SSE event', async () => {
  vi.useFakeTimers()
  const cancel = vi.fn()
  const response = new Response(new ReadableStream({ cancel }), { headers: { "Content-Type": "text/event-stream" } })
  const stream = speechApi.processSSEStream(response, undefined, 15000)
  const ended = stream.next()
  await vi.advanceTimersByTimeAsync(15001)
  expect((await ended).done).toBe(true)
  expect(cancel).toHaveBeenCalledOnce()
})

it('heartbeats keep a live connection healthy without becoming visible text', async () => {
  vi.useFakeTimers()
  let writer!: ReadableStreamDefaultController
  const response = new Response(new ReadableStream({ start(controller) { writer = controller } }), { headers: { "Content-Type": "text/event-stream" } })
  const stream = speechApi.processSSEStream(response, undefined, 15000)
  for (let index = 0; index < 4; index++) {
    const next = stream.next()
    await vi.advanceTimersByTimeAsync(5000)
    writer.enqueue(new TextEncoder().encode('data: {"type":"heartbeat"}\n\n'))
    expect((await next).value).toEqual({ type: 'heartbeat' })
  }
  writer.close()
  expect((await stream.next()).done).toBe(true)
})


it('aborts a request with missing response headers so its command can reconnect', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })))
  const request = speechApi.aiSpeakStream('game', 'ai')
  const rejected = expect(request).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(30001)
  await rejected
})
