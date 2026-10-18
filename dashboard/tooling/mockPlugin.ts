import { readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

// Each server session moves the documented sample to now, preserving its JST times and intervals.
const fixtureEpoch = Date.parse('2026-10-18T21:48:07+09:00')
const offset = Math.floor(Date.now() / 1000) * 1000 - fixtureEpoch
const fixtures = new Set(['EnumReserveInfo', 'EnumRecInfo', 'EnumTunerReserveInfo', 'EnumService'])
function shiftDates(value: unknown): unknown {
  if (typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value)) {
    return new Date(Date.parse(value) + offset + 9 * 3600_000).toISOString().replace('.000Z', '+09:00')
  }
  if (Array.isArray(value)) return value.map(shiftDates)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, val]) => [key, shiftDates(val)]))
  return value
}
async function middleware(req: IncomingMessage, res: ServerResponse, next: () => void) {
  const url = new URL(req.url ?? '/', 'http://localhost')
  const name = url.pathname === '/dashboard.json' ? 'dashboard' : url.pathname.startsWith('/api/') && url.searchParams.get('json') === '1' ? url.pathname.slice(5) : ''
  if (name !== 'dashboard' && !fixtures.has(name)) return next()
  try {
    const data: unknown = JSON.parse(await readFile(new URL(`../mock/${name}.json`, import.meta.url), 'utf8'))
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
    res.end(JSON.stringify(name === 'dashboard' ? data : shiftDates(data)))
  } catch {
    res.writeHead(500, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ err: 'モックを読み込めません' }))
  }
}
export function mockPlugin(previewMock: boolean): Plugin {
  return {
    name: 'dashboard-development-mock',
    configureServer(server) { server.middlewares.use((req, res, next) => { void middleware(req, res, next) }) },
    configurePreviewServer(server) {
      if (previewMock) server.middlewares.use((req, res, next) => { void middleware(req, res, next) })
    },
  }
}
