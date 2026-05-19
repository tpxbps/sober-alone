import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  build: {
    target: 'es2020',
  },
  esbuild: {
    target: 'es2020',
  },
  server: {
    proxy: {
      '/audio/scripts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/images/scripts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
