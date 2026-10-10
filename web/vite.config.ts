import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API goes to the gateway (make run-gateway); in production the gateway
// serves this build itself, so /api is same-origin either way.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
