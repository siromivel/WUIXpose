import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Django serves the API and tiles; in development Vite forwards those paths to it so the app
// can use same-origin URLs and needs no CORS setup.
const django = process.env.DJANGO_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // MapLibre alone is ~1 MB minified; one chunk is fine for an app that is mostly the map.
  build: { chunkSizeWarningLimit: 1600 },
  worker: { format: 'es' },
  server: {
    proxy: {
      '/api': django,
      '/tiles': django,
    },
  },
})
