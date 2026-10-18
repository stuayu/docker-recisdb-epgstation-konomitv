import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { CONFIG_ERROR, parseConfigText } from '../lib/config'
import type { DashboardConfig } from '../lib/config'
import { getSchedule, parseRecordings, parseReserves, parseTuners, parseEpgState, recentRecordings } from '../lib/edcb'
import type { EDCBRecording, EDCBReserve, EDCBTuner } from '../lib/edcb'
import { resolveService } from '../lib/urls'
import { checkService } from '../lib/status'

export function useDashboard() {
  const config = shallowRef<DashboardConfig>()
  const configError = ref('')
  const now = ref(Date.now())
  const reserves = shallowRef<EDCBReserve[]>([])
  const recordings = shallowRef<EDCBRecording[]>([])
  const tuners = shallowRef<EDCBTuner[]>([])
  const loading = ref(true)
  const errors = ref({ reserves: '', recordings: '', tuners: '', epg: '' })
  const epg = ref<'ready' | 'empty'>('ready')
  const lastUpdated = ref<number>()
  const statuses = ref<Record<string, 'up' | 'down' | 'unknown'>>({})
  const services = computed(() => config.value?.services.map(service => ({ ...service, endpoints: resolveService(service, config.value!, window.location) })) ?? [])
  const schedule = computed(() => getSchedule(reserves.value, tuners.value, now.value))
  const recent = computed(() => recentRecordings(recordings.value))
  const enabled = computed(() => config.value?.edcb.api !== false)
  const summaryError = computed(() => !enabled.value ? 'EDCB の情報表示は無効です' : errors.value.reserves || errors.value.tuners ? 'EDCB の情報を取得できません' : '')
  const controllers = new Set<AbortController>()
  let stopped = false
  let refreshing = false
  let checking = false
  const intervals: ReturnType<typeof setInterval>[] = []

  async function fetchText(url: string) {
    const controller = new AbortController()
    controllers.add(controller)
    const timer = setTimeout(() => controller.abort(), 8000)
    try {
      const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return await response.text()
    } finally { clearTimeout(timer); controllers.delete(controller) }
  }
  async function refresh() {
    if (!enabled.value || refreshing || stopped) { loading.value = false; return }
    refreshing = true
    const jobs = [
      { key: 'reserves' as const, run: async (data: unknown) => { reserves.value = parseReserves(data) } },
      { key: 'recordings' as const, run: async (data: unknown) => { recordings.value = parseRecordings(data) } },
      { key: 'tuners' as const, run: async (data: unknown) => { tuners.value = parseTuners(data) } },
      { key: 'epg' as const, run: async (data: unknown) => { epg.value = parseEpgState(data) } },
    ]
    const names = ['EnumReserveInfo', 'EnumRecInfo', 'EnumTunerReserveInfo', 'EnumService']
    let succeeded = false
    await Promise.all(jobs.map(async (job, index) => {
      try {
        const data: unknown = JSON.parse(await fetchText(`./api/${names[index]}?json=1`))
        if (stopped) return
        await job.run(data)
        errors.value[job.key] = ''
        succeeded = true
      } catch {
        if (stopped) return
        errors.value[job.key] = 'EDCB の情報を取得できません'
        if (job.key === 'reserves') reserves.value = []
        if (job.key === 'recordings') recordings.value = []
        if (job.key === 'tuners') tuners.value = []
      }
    }))
    if (succeeded && !stopped) lastUpdated.value = Date.now()
    loading.value = false
    refreshing = false
  }
  async function check() {
    if (checking || stopped) return
    checking = true
    await Promise.all(services.value.map(async service => {
      const url = service.endpoints.primary?.url
      const state = service.local || !url ? 'unknown' : await checkService(url, window.location.protocol)
      if (!stopped) statuses.value[service.id] = state
    }))
    checking = false
  }
  function visible() {
    if (document.visibilityState === 'visible') { now.value = Date.now(); void check(); void refresh() }
  }
  onMounted(async () => {
    intervals.push(setInterval(() => { now.value = Date.now() }, 1000))
    try {
      const result = parseConfigText(await fetchText('./dashboard.json'))
      if (result.ok) { config.value = result.value; document.title = result.value.title }
      else configError.value = result.error
    } catch { configError.value = CONFIG_ERROR }
    if (stopped) return
    await Promise.all([refresh(), check()])
    intervals.push(setInterval(() => { void refresh() }, 60_000), setInterval(() => { void check() }, 30_000))
    document.addEventListener('visibilitychange', visible)
  })
  onUnmounted(() => {
    stopped = true
    intervals.forEach(clearInterval)
    controllers.forEach(controller => controller.abort())
    document.removeEventListener('visibilitychange', visible)
  })
  return { config, configError, now, services, schedule, recent, errors, loading, epg, enabled, summaryError, lastUpdated, statuses, refresh }
}
