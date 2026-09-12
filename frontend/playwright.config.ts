import { defineConfig } from '@playwright/test'

const port = Number(process.env.PLAYWRIGHT_PORT || 4173)

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: `http://127.0.0.1:${port}`, channel: process.env.PLAYWRIGHT_CHANNEL },
  webServer: {
    command: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port ${port} --strictPort`,
    port,
    reuseExistingServer: !process.env.CI && !process.env.PLAYWRIGHT_PORT,
  },
})
