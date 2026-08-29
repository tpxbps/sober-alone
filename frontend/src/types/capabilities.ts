export interface ProviderCapability {
  id: string;
  name: string;
  provider: string;
  provider_name: string;
  model: string;
  configured: boolean;
  reason: string;
}

export interface FeatureCapability {
  enabled: boolean;
  reason: string;
}

export interface SystemCapabilities {
  mode: string;
  models: ProviderCapability[];
  features: {
    rag: FeatureCapability;
    image: FeatureCapability;
    static_tts: FeatureCapability;
    streaming_tts: FeatureCapability;
  };
}

export type ModelHealthStatus = 'normal' | 'slow' | 'unavailable';

export interface ModelHealthItem {
  model: string;
  status: ModelHealthStatus;
  /** @deprecated Use first_token_latency_ms. */
  latency_ms: number | null;
  first_token_latency_ms: number | null;
  reaction_latency_ms: number | null;
  slow_dimensions: Array<'speech' | 'reaction'>;
  message: string;
  checked_at: string;
}

export interface ModelHealthResponse {
  models: ModelHealthItem[];
  cached: boolean;
}
