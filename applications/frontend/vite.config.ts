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
      unstubEnvs: true,
      unstubGlobals: true,
    },
    server: {
      host: true,
      port: 5173,
      // The real backend serves /api; MediaMTX serves /camNN/, the camera
      // streams the tiles play. Both are proxied so a dev server and the
      // nginx image put them at the same paths.
      proxy: {
        '/api': { target: env.VITE_API_TARGET ?? 'http://localhost:8000', changeOrigin: true },
        '^/cam\\d+/': { target: env.VITE_CAMERA_TARGET ?? 'http://localhost:8888', changeOrigin: true },
      },
    },
  }
})
