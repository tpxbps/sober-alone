export interface ProviderCapability {
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
