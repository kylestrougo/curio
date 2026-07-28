import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Flask backend in dev. Everything it owns is proxied through so that
// `npm run dev` behaves exactly like the production single-origin deploy.
const backend = 'http://127.0.0.1:5000';

export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
      '/d': { target: backend, changeOrigin: false },
      '/unsub': { target: backend, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
