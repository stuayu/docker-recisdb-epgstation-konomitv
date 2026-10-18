import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { mockPlugin } from './tooling/mockPlugin.ts'
import { bundledLicenses } from './tooling/licenses.ts'

export default defineConfig(({ mode }) => ({
  base: './',
  publicDir: false,
  plugins: [vue(), mockPlugin(mode === 'mock'), bundledLicenses()],
  build: { outDir: 'dist', assetsDir: 'dash-assets', assetsInlineLimit: 0 },
  server: { port: 5179, strictPort: true },
  preview: { port: 5179, strictPort: true },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
}))
