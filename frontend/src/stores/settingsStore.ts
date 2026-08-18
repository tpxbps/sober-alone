import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SettingsState {
  ttsEnabled: boolean; // TTS 语音播报开关 (Beta)
  setTtsEnabled: (enabled: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ttsEnabled: false,
      setTtsEnabled: (enabled) => set({ ttsEnabled: enabled }),
    }),
    { name: 'sober_alone_settings' }
  )
);
