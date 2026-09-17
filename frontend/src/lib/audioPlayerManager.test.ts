import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { audioPlayerManager } from './audioPlayerManager'

class FakeAudio {
  paused = true
  currentTime = 0
  duration = 1
  src = ''
  play = vi.fn(async () => { this.paused = false })
  pause() { this.paused = true }
  removeAttribute() {}
  load() {}
}

describe('streaming audio completion', () => {
  beforeEach(() => {
    vi.stubGlobal('Audio', FakeAudio)
    vi.stubGlobal('requestAnimationFrame', () => 1)
    vi.stubGlobal('cancelAnimationFrame', () => {})
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
  })
  afterEach(() => {
    audioPlayerManager.stop()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })
  it('buffers unsupported MP3 MediaSource and starts only after complete audio', async () => {
    vi.stubGlobal('MediaSource', undefined)
    await audioPlayerManager.startStream()
    await audioPlayerManager.appendChunk('YWJj')
    expect(audioPlayerManager.getIsPlaying()).toBe(false)
    expect(audioPlayerManager.endStream(9101)).toBe('blob:test')
    expect(audioPlayerManager.getIsPlaying()).toBe(true)
    expect(audioPlayerManager.getCachedUrl(9101)).toBe('blob:test')
  })
  it('does not cache or replay cancelled buffered audio', async () => {
    vi.stubGlobal('MediaSource', undefined)
    await audioPlayerManager.startStream()
    await audioPlayerManager.appendChunk('YWJj')
    audioPlayerManager.stop()
    await audioPlayerManager.appendChunk('ZGVm')
    expect(audioPlayerManager.endStream(9102)).toBeNull()
    expect(audioPlayerManager.getIsPlaying()).toBe(false)
  })
  it('waits for the final SourceBuffer update before ending the media stream', async () => {
    class Buffer extends EventTarget {
      updating = false
      mode = ''
      appendBuffer() { this.updating = true }
      complete() { this.updating = false; this.dispatchEvent(new Event('updateend')) }
    }
    const buffer = new Buffer()
    const finish = vi.fn()
    class Source extends EventTarget {
      static isTypeSupported() { return true }
      readyState = 'open'
      constructor() { super(); queueMicrotask(() => this.dispatchEvent(new Event('sourceopen'))) }
      addSourceBuffer() { return buffer }
      endOfStream() { finish(); this.readyState = 'ended' }
    }
    vi.stubGlobal('MediaSource', Source)
    await audioPlayerManager.startStream()
    await audioPlayerManager.appendChunk('YWJj')
    await audioPlayerManager.appendChunk('ZGVm')
    audioPlayerManager.endStream(9103)
    expect(finish).not.toHaveBeenCalled()
    buffer.complete()
    expect(finish).not.toHaveBeenCalled()
    buffer.complete()
    expect(finish).toHaveBeenCalledOnce()
  })
})
