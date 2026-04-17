import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SettingsState {
  bgmEnabled: boolean;
  bgmVolume: number; // 0~1
  ttsEnabled: boolean; // TTS 语音播报开关 (Beta)
  setBgmEnabled: (enabled: boolean) => void;
  setBgmVolume: (volume: number) => void;
  setTtsEnabled: (enabled: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      bgmEnabled: true,
      bgmVolume: 0.15,
      ttsEnabled: false,
      setBgmEnabled: (enabled) => set({ bgmEnabled: enabled }),
      setBgmVolume: (volume) => set({ bgmVolume: Math.max(0, Math.min(1, volume)) }),
      setTtsEnabled: (enabled) => set({ ttsEnabled: enabled }),
    }),
    { name: 'sober_alone_settings' }
  )
);
