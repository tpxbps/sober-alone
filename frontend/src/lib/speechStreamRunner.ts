import type { StreamingMessage } from '@/types/game'

export type SpeechStreamHandlers = Partial<{
  [Type in StreamingMessage['type']]: (
    message: StreamingMessage & { type: Type },
  ) => void | Promise<void>
}>

export async function runSpeechStream(
  stream: AsyncIterable<StreamingMessage>,
  handlers: SpeechStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  for await (const message of stream) {
    if (signal?.aborted) return
    const handler = handlers[message.type] as
      | ((item: StreamingMessage) => void | Promise<void>)
      | undefined
    if (handler) await handler(message)
  }
}
