import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SettingsState {
  lobbyMotionEnabled: boolean;
  setLobbyMotionEnabled: (enabled: boolean) => void;
  ttsEnabled: boolean; // TTS 语音播报开关 (Beta)
  setTtsEnabled: (enabled: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      lobbyMotionEnabled: true,
      setLobbyMotionEnabled: (enabled) => set({ lobbyMotionEnabled: enabled }),
      ttsEnabled: false,
      setTtsEnabled: (enabled) => set({ ttsEnabled: enabled }),
    }),
    { name: 'sober_alone_settings' }
  )
);
