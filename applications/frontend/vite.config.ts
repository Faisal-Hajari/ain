import { fileURLToPath, URL } from 'node:url'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')

  return {
    plugins: [
      react({ babel: { plugins: [['babel-plugin-react-compiler', {}]] } }),
      tailwindcss(),
    ],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    build: {
      rollupOptions: {
        output: {
          // Recharts is most of the bundle and changes far less often than the
          // app does; splitting it keeps it cached across deploys.
          manualChunks: { charts: ['recharts'] },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
    },
    server: {
      host: true,
      port: 5173,
      // Only reached when VITE_API_MOCK is off: the real backend serves /api.
      proxy: {
        '/api': { target: env.VITE_API_TARGET ?? 'http://localhost:8000', changeOrigin: true },
      },
    },
  }
})
