import type { SystemCapabilities } from '@/types/capabilities'
import type { AIModelOption } from '@/types/game'

export function configuredModels(
  capabilities: SystemCapabilities,
): AIModelOption[] {
  return capabilities.models
    .filter((item) => item.configured)
    .map((item) => ({ id: item.id, name: item.name, provider: item.provider }))
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
