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
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          ui: ['framer-motion', 'lucide-react'],
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
  esbuild: {
    target: 'es2020',
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/audio/scripts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/images/scripts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
