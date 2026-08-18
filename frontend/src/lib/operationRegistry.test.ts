import { describe, expect, it } from 'vitest'

import { OperationRegistry } from './operationRegistry'

describe('OperationRegistry', () => {
  it('aborts the previous operation with the same key', () => {
    const registry = new OperationRegistry()
    const first = registry.start('speech')
    const second = registry.start('speech')

    expect(first.signal.aborted).toBe(true)
    expect(registry.isCurrent('speech', second)).toBe(true)
  })

  it('aborts the whole pending chain on session reset', () => {
    const registry = new OperationRegistry()
    const speech = registry.start('speech')
    const pendingHuman = registry.start('pending-human')

    registry.abortAll()

    expect(speech.signal.aborted).toBe(true)
    expect(pendingHuman.signal.aborted).toBe(true)
  })
})
