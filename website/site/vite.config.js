import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Beacon front door — Vite + React, prerendered to static HTML at build time
// (see scripts/prerender.mjs). Output assets land in dist/assets/ and are
// synced into ../ (website/) by scripts/sync-to-website.mjs so the existing
// Python deploy pipeline ships them unchanged.
const isSSR = process.env.BEACON_SSR === '1'

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: isSSR
    ? {
        // SSR bundle: one predictable file the prerenderer imports.
        ssr: 'src/entry-server.jsx',
        outDir: 'dist/server',
        rollupOptions: {
          output: { entryFileNames: 'entry-server.js', chunkFileNames: '[name].js' },
        },
      }
    : {
        assetsDir: 'assets',
        cssCodeSplit: false,
        modulePreload: { polyfill: false },
        rollupOptions: {
          output: {
            entryFileNames: 'assets/beacon-[hash].js',
            chunkFileNames: 'assets/beacon-[hash].js',
            assetFileNames: 'assets/beacon-[hash][extname]',
          },
        },
      },
})
