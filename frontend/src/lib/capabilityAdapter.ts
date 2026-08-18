import type { SystemCapabilities } from '@/types/capabilities'
import type { AIModelOption } from '@/types/game'

export function configuredModels(
  models: AIModelOption[],
  capabilities: SystemCapabilities,
): AIModelOption[] {
  const configured = new Set(
    capabilities.models.filter((item) => item.configured).map((item) => item.model),
  )
  return models.filter((model) => configured.has(model.id))
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
