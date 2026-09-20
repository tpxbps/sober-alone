import type { SystemCapabilities } from '@/types/capabilities'
import type { AIModelOption } from '@/types/game'

const preferredGameModels = ['deepseek-flash', 'qwen3.8-flash', 'glm-5.3-flash']

/** Use the same registry labels for the picker and historical chat bubbles. */
export function modelDisplayName(id: string | null | undefined, models: SystemCapabilities['models']): string {
  if (!id) return ''
  const aliases: Record<string, string> = {
    'deepseek-v4-flash': 'deepseek-flash',
    'deepseek-v4-flash-vision-exp': 'deepseek-flash',
    'deepseek-v4.1-flash': 'deepseek-flash',
  }
  const canonical = aliases[id.toLowerCase()] ?? id
  const spec = models.find(model => model.id === canonical || model.model === id)
  return spec ? spec.name.toLowerCase() : ''
}

function modelOrder(model: AIModelOption): number {
  if (model.tier === 'frontier') return -1
  const preferred = preferredGameModels.indexOf(model.id)
  return preferred < 0 ? preferredGameModels.length : preferred
}

export function configuredModels(
  capabilities: SystemCapabilities,
): AIModelOption[] {
  return capabilities.models
    .filter((item) => item.configured)
    .map((item) => ({ id: item.id, name: item.name.toLowerCase(), provider: item.provider, ...(item.tier ? { tier: item.tier } : {}) }))
    .sort((left, right) => modelOrder(left) - modelOrder(right))
}

export function ttsCapability(capabilities: SystemCapabilities) {
  const enabled =
    capabilities.features.streaming_tts.enabled || capabilities.features.static_tts.enabled
  return {
    enabled,
    reason: enabled
      ? '已配置语音供应商'
      : `${capabilities.features.streaming_tts.reason}；${capabilities.features.static_tts.reason}`,
  }
}
