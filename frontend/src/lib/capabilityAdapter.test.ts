import { describe, expect, it } from 'vitest'

import type { SystemCapabilities } from '../types/capabilities'
import { configuredModels, modelDisplayName, ttsCapability } from './capabilityAdapter'

const capabilities: SystemCapabilities = {
  mode: 'local-first-single-user-single-process',
  models: [
    {
      id: 'deepseek-flash',
      name: 'DeepSeek V4 Flash',
      provider: 'deepseek',
      provider_name: 'DeepSeek',
      model: 'deepseek-flash',
      configured: true,
      reason: '已配置',
    },
    {
      id: 'step-3.5-flash',
      name: 'Step 3.5 Flash',
      provider: 'stepfun',
      provider_name: '阶跃星辰',
      model: 'step-3.5-flash',
      configured: false,
      reason: '未配置 STEPFUN_API_KEY',
    },
  ],
  features: {
    rag: { enabled: false, reason: '未配置 ZHIPUAI_API_KEY' },
    image: { enabled: false, reason: '未配置 DOUBAO_API_KEY' },
    static_tts: { enabled: false, reason: '未配置 MIMO_API_KEY' },
    streaming_tts: { enabled: false, reason: '未配置 STEPFUN_API_KEY' },
  },
}

describe('capability adapters', () => {
  it('uses identical picker and chat labels, including provider IDs and old aliases', () => {
    const source = { ...capabilities, models: [
      { ...capabilities.models[0], name: 'deepSeek-v4.1-flash' },
      { ...capabilities.models[0], id: 'doubao-lite', model: 'doubao-seed-2-0-lite-260215', name: 'doubao-seed-2.0-lite' },
    ] }
    for (const option of configuredModels(source)) expect(modelDisplayName(option.id, source.models)).toBe(option.name)
    expect(modelDisplayName('doubao-seed-2-0-lite-260215', source.models)).toBe('doubao-seed-2.0-lite')
    expect(modelDisplayName('deepseek-v4-flash', source.models)).toBe('deepseek-v4.1-flash')
    expect(modelDisplayName('unavailable', source.models)).toBe('')
  })
  it('keeps frontier models first and prioritizes common models with lowercase labels', () => {
    const source = { ...capabilities, models: [
      { ...capabilities.models[0], id: 'ling-3.0-flash', name: 'Ling-3.0-flash' },
      { ...capabilities.models[0], id: 'glm-5.3-flash', name: 'GLM-5.3-flash' },
      { ...capabilities.models[0], id: 'kimi-k3', name: 'Kimi K3', tier: 'frontier' as const },
      capabilities.models[0],
      { ...capabilities.models[0], id: 'qwen3.8-flash', name: 'Qwen3.8-flash' },
    ] }
    const models = configuredModels(source)
    expect(models.map(model => model.id)).toEqual(['kimi-k3', 'deepseek-flash', 'qwen3.8-flash', 'glm-5.3-flash', 'ling-3.0-flash'])
    expect(models.every(model => model.name === model.name.toLowerCase())).toBe(true)
  })

  it('normalizes the legacy deepSeek V4 display name without changing model IDs', () => {
    const source = { ...capabilities, models: [{ ...capabilities.models[0], name: 'deepSeek-v4.1-flash' }] }
    expect(configuredModels(source)[0]).toMatchObject({ id: 'deepseek-flash', name: 'deepseek-v4.1-flash' })
    expect(source.models[0].name).toBe('deepSeek-v4.1-flash')
  })

  it('exposes only models whose provider key is configured', () => {
    expect(configuredModels(capabilities).map((model) => model.id)).toEqual([
      'deepseek-flash',
    ])
  })

  it('explains why optional TTS is disabled', () => {
    expect(ttsCapability(capabilities)).toEqual({
      enabled: false,
      reason: '未配置 STEPFUN_API_KEY；未配置 MIMO_API_KEY',
    })
  })
})
