import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // Load every variable (not only VITE_*) from .env files and the environment, for config here.
  const env = loadEnv(mode, process.cwd(), '')
  // Django serves the API and tiles; in development Vite forwards those paths to it so the app
  // can use same-origin URLs and needs no CORS setup.
  const django = env.DJANGO_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    // MapLibre alone is ~1 MB minified; one chunk is fine for an app that is mostly the map.
    build: { chunkSizeWarningLimit: 1600 },
    worker: { format: 'es' },
    server: {
      // changeOrigin stays off so Django sees this server's Host and writes TileJSON tile URLs
      // that point back here; with it on, tiles would come straight from Django, cross-origin.
      proxy: {
        '/api': { target: django, changeOrigin: false },
        '/tiles': { target: django, changeOrigin: false },
      },
    },
  }
})
