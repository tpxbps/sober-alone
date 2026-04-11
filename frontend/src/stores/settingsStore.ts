import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SettingsState {
  bgmEnabled: boolean;
  bgmVolume: number; // 0~1
  setBgmEnabled: (enabled: boolean) => void;
  setBgmVolume: (volume: number) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      bgmEnabled: true,
      bgmVolume: 0.15,
      setBgmEnabled: (enabled) => set({ bgmEnabled: enabled }),
      setBgmVolume: (volume) => set({ bgmVolume: Math.max(0, Math.min(1, volume)) }),
    }),
    { name: 'sober_alone_settings' }
  )
);
