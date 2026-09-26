import { afterEach, expect, it, vi } from 'vitest'
import { speechApi } from './api'

afterEach(() => vi.useRealTimers())

it('closes the transport after 15 seconds without an SSE event', async () => {
  vi.useFakeTimers()
  const cancel = vi.fn()
  const response = new Response(new ReadableStream({ cancel }))
  const stream = speechApi.processSSEStream(response, undefined, 15000)
  const rejected = expect(stream.next()).rejects.toThrow('连接暂时中断')
  await vi.advanceTimersByTimeAsync(15001)
  await rejected
  expect(cancel).toHaveBeenCalledOnce()
})

it('heartbeats keep a live connection healthy without becoming visible text', async () => {
  vi.useFakeTimers()
  let writer!: ReadableStreamDefaultController
  const response = new Response(new ReadableStream({ start(controller) { writer = controller } }))
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
