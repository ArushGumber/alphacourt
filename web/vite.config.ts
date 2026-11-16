import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base: './' keeps every asset path relative, so the built site works from any folder.
// For live work in development: VITE_API_BASE=/ VITE_API_PROXY=http://127.0.0.1:8000 npm run dev
// sends /api and /mcp from the dev server to the gateway.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY
  return {
    base: './',
    plugins: [react(), tailwindcss()],
    server: target ? { proxy: { '/api': { target, changeOrigin: true }, '/mcp': { target, changeOrigin: true } } } : undefined,
    build: { target: 'es2022', chunkSizeWarningLimit: 900 },
  }
})
