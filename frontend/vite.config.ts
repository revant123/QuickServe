/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs separately (Docker Compose publishes it on localhost:8001).
// In development Vite forwards /api to it, so the browser sees ONE origin and
// no CORS setup is needed. In Kubernetes the Gateway does the same job:
// /api goes to the API, everything else to this app's nginx.
const api = process.env.QUICKSERVE_API ?? 'http://localhost:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180, // QuickKart uses 8080; 5173 is left alone in case another Vite app is running
    strictPort: true,
    proxy: { '/api': api },
  },
  preview: { port: 5181, strictPort: true },
  build: {
    // Libraries change rarely, the app's own code changes every release. In
    // separate files (each named by a hash of its content), a new release only
    // makes phones download the small app file again; the vendor file stays
    // cached. The real size budget is checked by scripts/check-size.mjs.
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [{ name: 'vendor', test: /node_modules[\\/](react|react-dom|react-router|scheduler|@tanstack)[\\/]/ }],
        },
      },
    },
    chunkSizeWarningLimit: 300,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
