import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => ({
  ...http, interceptors: { request: { use: vi.fn() } },
}) } }))
beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); vi.useFakeTimers(); vi.setSystemTime(100000) })
afterEach(() => { vi.useRealTimers() })
const response = (probing = false, max_age_seconds = 1800, model = 'fast') => ({ data: {
  models: [{ model, status: 'normal' }], cached: !probing, probing, max_age_seconds,
} })

it('shares lobby polling, dialog subscriptions and manual clicks without a second run', async () => {
  http.get.mockResolvedValueOnce(response(true, 0)).mockResolvedValueOnce(response(false))
  const { systemApi, subscribeModelHealth } = await import('./api')
  const seen: string[][] = []
  const unsubscribe = subscribeModelHealth((value) => seen.push(value.models.map((m) => m.model)))
  const lobby = systemApi.getModelHealth()
  const dialog = systemApi.getModelHealth()
  const manualDuringProbe = systemApi.getModelHealth(true)
  await vi.advanceTimersByTimeAsync(0)
  expect(seen).toEqual([['fast']])
  expect(http.get).toHaveBeenCalledTimes(1)
  expect(http.post).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1999)
  expect(http.get).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  expect((await lobby).probing).toBe(false)
  expect(await dialog).toEqual(await manualDuringProbe)
  expect(http.get).toHaveBeenCalledTimes(2)
  unsubscribe()
  await systemApi.getModelHealth()
  expect(http.get).toHaveBeenCalledTimes(2)
})

it('honors the remaining server cache lifetime and never extends it to 30 minutes', async () => {
  http.get.mockResolvedValueOnce(response(false, 1)).mockResolvedValueOnce(response(false))
  const { systemApi } = await import('./api')
  await systemApi.getModelHealth()
  await vi.advanceTimersByTimeAsync(999)
  await systemApi.getModelHealth()
  expect(http.get).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  await systemApi.getModelHealth()
  expect(http.get).toHaveBeenCalledTimes(2)
})

it('refreshes a completed cache once with POST, then polls with GET', async () => {
  http.get.mockResolvedValue(response(false))
  http.post.mockResolvedValueOnce(response(true, 0))
  const { systemApi } = await import('./api')
  await systemApi.getModelHealth()
  const first = systemApi.getModelHealth(true)
  const second = systemApi.getModelHealth(true)
  await vi.advanceTimersByTimeAsync(2000)
  expect(await first).toEqual(await second)
  expect(http.post).toHaveBeenCalledTimes(1)
  expect(http.get).toHaveBeenCalledTimes(2)
})

it('does not cache request failures and allows the dialog to retry', async () => {
  http.get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response(false))
  const { systemApi } = await import('./api')
  await expect(systemApi.getModelHealth()).rejects.toThrow('offline')
  expect((await systemApi.getModelHealth()).models).toHaveLength(1)
  expect(http.get).toHaveBeenCalledTimes(2)
})
