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
    // The seed pool lives one level up in shared/ (the backend's warm-cache
    // job reads the same file); without this the dev server refuses to serve
    // imports from outside the frontend root. Build output is unaffected.
    fs: { allow: ['..'] },
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
