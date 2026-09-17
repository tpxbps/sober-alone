import { defineConfig } from '@playwright/test'

const port = Number(process.env.PLAYWRIGHT_PORT || 4173)

export default defineConfig({
  testDir: './e2e',
  projects: [
    { name: 'flows', testIgnore: '**/lobby-alignment.spec.ts' },
    // Pixel comparisons require the live renderer. Run alone after UI flows so
    // competing GPU contexts do not legitimately trigger the low-FPS fallback.
    {
      name: 'webgl-pixels',
      testMatch: '**/lobby-alignment.spec.ts',
      dependencies: ['flows'],
      workers: 1,
      // Match the full browser compositor instead of the legacy headless shell.
      use: { channel: process.env.PLAYWRIGHT_CHANNEL || 'chromium' },
    },
  ],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.PLAYWRIGHT_CHANNEL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port ${port} --strictPort`,
    port,
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === '1' || (!process.env.CI && !process.env.PLAYWRIGHT_PORT),
  },
})
