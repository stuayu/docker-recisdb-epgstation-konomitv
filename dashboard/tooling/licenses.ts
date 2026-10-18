import { readFile } from 'node:fs/promises'
import type { Plugin } from 'vite'

export function bundledLicenses(): Plugin {
  return {
    name: 'dashboard-bundled-licenses',
    apply: 'build',
    async generateBundle() {
      const packages = ['vue', '@vue/runtime-dom', '@vue/runtime-core', '@vue/reactivity', '@vue/shared', '@fontsource-variable/archivo', '@fontsource-variable/jetbrains-mono', '@fontsource/ibm-plex-sans-jp']
      const notices = await Promise.all(packages.map(async name => `${name}\n${await readFile(new URL(`../node_modules/${name}/LICENSE`, import.meta.url), 'utf8')}`))
      this.emitFile({ type: 'asset', name: 'third-party-licenses.txt', source: notices.join('\n\n') })
    },
  }
}
