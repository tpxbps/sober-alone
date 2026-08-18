import { describe, expect, it } from 'vitest'

import type { StreamingMessage } from '@/types/game'
import { runSpeechStream } from './speechStreamRunner'

async function* messages(): AsyncGenerator<StreamingMessage> {
  yield { type: 'token', text: '雾' }
  yield { type: 'token', text: '港' }
  yield { type: 'speech_done' }
  yield { type: 'done', next_speaker_id: 'next' }
}

describe('runSpeechStream', () => {
  it('preserves event order and merges tokens in the consumer', async () => {
    const order: string[] = []
    let content = ''

    await runSpeechStream(messages(), {
      token: (message) => {
        content += message.text || ''
        order.push('token')
      },
      speech_done: () => {
        order.push('speech_done')
      },
      done: () => {
        order.push('done')
      },
    })

    expect(content).toBe('雾港')
    expect(order).toEqual(['token', 'token', 'speech_done', 'done'])
  })

  it('stops applying events after cancellation', async () => {
    const controller = new AbortController()
    const applied: string[] = []

    await runSpeechStream(
      messages(),
      {
        token: () => {
          applied.push('token')
          controller.abort()
        },
        done: () => {
          applied.push('done')
        },
      },
      controller.signal,
    )

    expect(applied).toEqual(['token'])
  })
})
