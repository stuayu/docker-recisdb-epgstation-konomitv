// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { createApp, nextTick } from 'vue'
import type { App as VueApp } from 'vue'
import App from './App.vue'
import config from '../mock/dashboard.json'
import reserves from '../mock/EnumReserveInfo.json'
import recordings from '../mock/EnumRecInfo.json'
import tuners from '../mock/EnumTunerReserveInfo.json'
import services from '../mock/EnumService.json'

let app: VueApp | undefined
let data: Record<string, unknown>
let fetcher: Mock<(input: string | URL) => Promise<Response>>
async function settle() {
  for (let index = 0; index < 30; index++) await Promise.resolve()
  await nextTick()
}
async function mount() {
  const root = document.createElement('div')
  document.body.append(root)
  app = createApp(App)
  app.mount(root)
  await settle()
  return root
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-18T21:48:07+09:00'))
  data = structuredClone({ '/dashboard.json': config, '/api/EnumReserveInfo': reserves, '/api/EnumRecInfo': recordings, '/api/EnumTunerReserveInfo': tuners, '/api/EnumService': services })
  fetcher = vi.fn(async (input: string | URL) => {
    const path = new URL(String(input), 'http://localhost').pathname
    return new Response(JSON.stringify(data[path] ?? {}), { status: 200 })
  })
  vi.stubGlobal('fetch', fetcher)
  document.title = '録画サーバー'
  delete document.documentElement.dataset.theme
  localStorage.clear()
})
afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.innerHTML = ''
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('dashboard integration', () => {
  it('renders API data, a single main anchor per service, local copy and eight physical tuners', async () => {
    const root = await mount()
    expect(root.querySelectorAll('.service-panel')).toHaveLength(6)
    expect(root.querySelectorAll('.service-panel__open')).toHaveLength(5)
    expect(root.querySelectorAll('a a')).toHaveLength(0)
    expect(root.querySelectorAll('.tuner-grid li')).toHaveLength(8)
    expect(root.querySelectorAll('.tuner-grid .tally--on')).toHaveLength(1)
    expect(root.querySelectorAll('.programme-panel:first-child .programme-list li')).toHaveLength(5)
    expect(root.querySelectorAll('.programme-panel:last-child .programme-list li')).toHaveLength(5)
    expect(root.querySelector('.programme-row--rec')?.textContent).toContain('録画中')
    expect(root.querySelector('.local-address a')).toBeNull()
    expect(document.title).toBe(config.title)
    expect(root.querySelector('a[href="/E3/#recinfo"]')).not.toBeNull()
  })
  it('uses only EDCB information when configuration is invalid', async () => {
    data['/dashboard.json'] = { title: '壊れた設定' }
    const root = await mount()
    expect(root.querySelector('[role="alert"]')?.textContent).toContain('make regen-config SERVICE=edcb')
    expect(root.querySelectorAll('.service-panel')).toHaveLength(0)
    expect(root.querySelectorAll('.programme-list li')).toHaveLength(10)
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('EnumReserveInfo'))).toBe(true)
  })
  it('keeps EDCB information when dashboard.json cannot be fetched', async () => {
    const normal = fetcher.getMockImplementation()!
    fetcher.mockImplementation(async (input: string | URL) => {
      if (String(input).includes('dashboard.json')) return new Response('missing', { status: 404 })
      return normal(input)
    })
    const root = await mount()
    expect(root.querySelector('[role="alert"]')).not.toBeNull()
    expect(root.querySelectorAll('.tuner-grid li')).toHaveLength(8)
  })
  it('distinguishes empty reserves, recordings and EPG from failed fetches', async () => {
    data['/api/EnumReserveInfo'] = []
    data['/api/EnumRecInfo'] = []
    data['/api/EnumService'] = { err: 'EPGデータを読み込み中、または存在しません' }
    const root = await mount()
    expect(root.textContent).toContain('予約はまだありません')
    expect(root.textContent).toContain('録画履歴はまだありません')
    expect(root.textContent).toContain('番組情報はまだ取得されていないか、読み込み中です')
    expect(root.querySelector('.status-message')).toBeNull()
  })
  it('shows API failures without claiming zero successful recordings or a current tally', async () => {
    data['/api/EnumReserveInfo'] = { err: 'failed' }
    data['/api/EnumRecInfo'] = '<html>error</html>'
    const root = await mount()
    expect(root.querySelector('.status-message')?.textContent).toContain('EDCB の情報を取得できません')
    expect(root.textContent).toContain('予約を取得できません')
    expect(root.textContent).toContain('録画履歴を取得できません')
    expect(root.querySelectorAll('.tally--on')).toHaveLength(0)
  })
  it('honors api=false, persists theme selection, and tolerates blocked localStorage', async () => {
    data['/dashboard.json'] = { ...config, edcb: { api: false } }
    const root = await mount()
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('./api/'))).toBe(false)
    expect(root.textContent).toContain('EDCB の情報表示は無効です')
    const darkButton = Array.from(root.querySelectorAll<HTMLButtonElement>('.theme-control button')).find(button => button.textContent === 'ダーク')!
    darkButton.click()
    await nextTick()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('edcb-dashboard-theme')).toBe('dark')
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const autoButton = root.querySelector<HTMLButtonElement>('.theme-control button')!
    expect(() => autoButton.click()).not.toThrow()
    expect(document.documentElement.dataset.theme).toBeUndefined()
    storage.mockRestore()
  })
  it('refreshes service checks at 30s, APIs at 60s and on visibility; releases timers', async () => {
    await mount()
    fetcher.mockClear()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetcher).toHaveBeenCalledTimes(5)
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('EnumReserveInfo'))).toBe(false)
    fetcher.mockClear()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetcher).toHaveBeenCalledTimes(9)
    fetcher.mockClear()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(fetcher).toHaveBeenCalledTimes(9)
    app!.unmount()
    app = undefined
    expect(vi.getTimerCount()).toBe(0)
  })
})
