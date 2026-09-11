import { describe, expect, it } from 'vitest'

import type { SystemCapabilities } from '../types/capabilities'
import { configuredModels, ttsCapability } from './capabilityAdapter'

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
