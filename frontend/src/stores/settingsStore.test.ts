import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

describe('voice setting persistence', () => {
  for (const [label, stored, expected] of [
    ['first visit', null, true],
    ['explicit off', { ttsEnabled: false }, false],
    ['explicit on', { ttsEnabled: true }, true],
    ['old settings without voice', { lobbyMotionEnabled: false }, true],
  ] as const) {
    it(label, async () => {
      const memory = new Map<string, string>();
      if (stored) memory.set('sober_alone_settings', JSON.stringify({ state: stored, version: 0 }));
      vi.stubGlobal('localStorage', {
        getItem: (key: string) => memory.get(key) ?? null,
        setItem: (key: string, value: string) => memory.set(key, value),
        removeItem: (key: string) => memory.delete(key),
      });
      const { useSettingsStore } = await import('./settingsStore');
      expect(useSettingsStore.getState().ttsEnabled).toBe(expected);
      useSettingsStore.getState().setTtsEnabled(false);
      await useSettingsStore.persist.rehydrate();
      expect(useSettingsStore.getState().ttsEnabled).toBe(false);
    });
  }
});
