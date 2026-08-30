import { describe, expect, it } from 'vitest'

import { assignModelsToAICharacters } from './modelAssignment'
import type { ModelHealthItem } from '@/types/capabilities'
import type { AIModelOption, Character } from '@/types/game'

const characters = ['human', 'ai-1', 'ai-2', 'ai-3'].map(
  (character_id, index) => ({ character_id, name: `角色${index}` }) as Character,
)
const models: AIModelOption[] = [
  { id: 'deepseek', name: 'DeepSeek', provider: 'deepseek' },
  { id: 'qwen', name: 'Qwen', provider: 'alibaba' },
  { id: 'mimo', name: 'MiMo', provider: 'mimo' },
  { id: 'glm', name: 'GLM', provider: 'zhipuai' },
]

function health(model: string, status: ModelHealthItem['status']): ModelHealthItem {
  return {
    model,
    status,
    latency_ms: null,
    first_token_latency_ms: null,
    reaction_latency_ms: null,
    slow_dimensions: [],
    failed_dimensions: [],
    message: '',
    checked_at: '',
  }
}

describe('assignModelsToAICharacters', () => {
  it('excludes slow models and does not repeat when responsive models are sufficient', () => {
    const result = assignModelsToAICharacters({
      characters,
      humanCharacterId: 'human',
      models,
      healthById: { mimo: health('mimo', 'slow') },
      random: () => 0.5,
    })

    expect(Object.values(result)).toHaveLength(3)
    expect(new Set(Object.values(result)).size).toBe(3)
    expect(Object.values(result)).not.toContain('mimo')
  })

  it('reuses responsive models evenly before considering a slow model', () => {
    const result = assignModelsToAICharacters({
      characters,
      humanCharacterId: 'human',
      models,
      healthById: {
        qwen: health('qwen', 'slow'),
        mimo: health('mimo', 'slow'),
        glm: health('glm', 'unavailable'),
      },
      random: () => 0.5,
    })

    expect(Object.values(result)).toEqual(['deepseek', 'deepseek', 'deepseek'])
  })

  it('falls back to slow models when every responsive model is unavailable', () => {
    const result = assignModelsToAICharacters({
      characters,
      humanCharacterId: 'human',
      models,
      healthById: {
        deepseek: health('deepseek', 'slow'),
        qwen: health('qwen', 'slow'),
        mimo: health('mimo', 'unavailable'),
        glm: health('glm', 'unavailable'),
      },
      random: () => 0.5,
    })

    expect(new Set(Object.values(result))).toEqual(new Set(['deepseek', 'qwen']))
  })
})
