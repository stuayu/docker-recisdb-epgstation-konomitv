<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDashboard } from './composables/useDashboard'
import { time, shortDate } from './lib/format'
import ServicePanel from './components/ServicePanel.vue'
import ProgrammeList from './components/ProgrammeList.vue'

const { config, configError, now, services, schedule, recent, errors, loading, epg, enabled, summaryError, lastUpdated, statuses } = useDashboard()
const theme = ref(document.documentElement.dataset.theme ?? 'auto')
const clock = computed(() => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(now.value).split(':'))
const date = computed(() => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }).format(now.value))
const reserveItems = computed(() => schedule.value.upcoming.map(item => ({ ...item, id: item.reserveID, station: item.stationName })))
const recordingItems = computed(() => recent.value.map(item => ({ ...item, station: item.serviceName })))
function selectTheme(value: string) {
  theme.value = value
  if (value === 'auto') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = value
  try { localStorage.setItem('edcb-dashboard-theme', value) } catch { /* Keep theme usable without storage. */ }
}
</script>

<template>
  <div class="dashboard">
    <header class="station-header">
      <div class="station-header__inner">
        <div class="station-identity"><p class="eyebrow">録画システム / ダッシュボード</p><h1>{{ config?.title ?? '録画サーバー' }}</h1><p class="host-name">{{ config?.host ?? 'EDCB' }}<span v-if="config?.httpsHost"> / {{ config.httpsHost }}</span></p></div>
        <div class="station-header__right">
          <fieldset class="theme-control"><legend class="sr-only">表示テーマ</legend><button v-for="option in [{ value: 'auto', name: '自動' }, { value: 'light', name: 'ライト' }, { value: 'dark', name: 'ダーク' }]" :key="option.value" type="button" :aria-pressed="theme === option.value" @click="selectTheme(option.value)">{{ option.name }}</button></fieldset>
          <div class="broadcast-clock" role="timer" aria-live="off" :aria-label="`${clock.join(':')} 日本標準時`"><span>{{ clock[0] }}:{{ clock[1] }}</span><span class="broadcast-clock__seconds">:{{ clock[2] }}</span></div>
          <p class="broadcast-date">{{ date }}<span>日本標準時</span></p>
        </div>
      </div>
      <div class="colour-bar" aria-hidden="true"><span v-for="index in 7" :key="index" :class="`identity--${index - 1}`"></span></div>
    </header>

    <main class="main-content">
      <p v-if="configError" class="notice" role="alert">設定ファイル dashboard.json を読めません。<code>make regen-config SERVICE=edcb</code> で作り直してください。</p>
      <section class="status-board" aria-label="録画とチューナーの状態">
        <p v-if="loading" class="status-message" role="status">EDCB の情報を読み込んでいます…</p>
        <p v-else-if="summaryError" class="status-message" role="status">{{ summaryError }}<a href="/E3/">EMWUI で確認する <span aria-hidden="true">↗</span></a></p>
        <template v-else>
          <div class="status-overview">
            <div class="metric"><span>予約</span><strong>{{ schedule.total }}</strong><span>件</span></div>
            <div class="metric" :class="{ 'metric--rec': schedule.recordingCount > 0 }"><span class="tally" :class="{ 'tally--on': schedule.recordingCount > 0 }" aria-hidden="true"></span><span>録画中</span><strong>{{ schedule.recordingCount }}</strong><span>件</span></div>
            <div class="next-programme"><span class="eyebrow">次の録画</span><p v-if="schedule.next"><time :datetime="schedule.next.startTime">{{ shortDate(schedule.next.startTime) }} {{ time(schedule.next.startTime) }}</time><span :title="schedule.next.title">{{ schedule.next.title }}</span></p><p v-else>次の録画予約はありません</p></div>
          </div>
          <div class="tuner-heading"><span>チューナー <strong>{{ schedule.tuners.length }}</strong> 本</span><small>録画状態は予約の割当・時刻から判定</small></div>
          <ul v-if="schedule.tuners.length" class="tuner-grid">
            <li v-for="(tuner, index) in schedule.tuners" :key="tuner.id">
              <div class="tuner-label"><span class="tally" :class="{ 'tally--on': tuner.recording }" aria-hidden="true"></span><span class="tuner-number">{{ String(index + 1).padStart(2, '0') }}</span><span :class="{ 'rec-label': tuner.recording }">{{ tuner.recording ? 'REC' : '待機' }}</span></div>
              <p class="tuner-name" :title="tuner.name">{{ tuner.name }}</p>
              <p v-if="tuner.current" class="tuner-next" :title="tuner.current.title">録画中 {{ tuner.current.title }}</p><p class="tuner-next" :title="tuner.next?.title">{{ tuner.next ? `次 ${shortDate(tuner.next.startTime)} ${time(tuner.next.startTime)} ${tuner.next.title}` : '次の予約なし' }}</p>
            </li>
          </ul>
          <p v-else class="subtle-message">チューナーはまだ登録されていません。<a href="/E3/">EMWUI で設定を確認</a></p>
        </template>
      </section>
      <p v-if="enabled && !loading && epg === 'empty' && !errors.epg" class="notice" role="status">番組情報はまだ取得されていないか、読み込み中です。<a href="/E3/">番組表を確認する</a></p>
      <p v-if="enabled && errors.epg" class="subtle-message" role="status">番組情報の取得状況を確認できません。<a href="/E3/">番組表を確認する</a></p>

      <section v-if="services.length" class="systems-section" aria-labelledby="systems-title">
        <div class="section-heading"><h2 id="systems-title">システム</h2><span class="section-caption">{{ services.length }} つのシステムを、この場所から。</span></div>
        <div class="service-grid"><ServicePanel v-for="(service, index) in services" :key="service.id" :service="service" :endpoints="service.endpoints" :index="index" :status="statuses[service.id] ?? 'unknown'" /></div>
      </section>
      <div class="programme-columns">
        <ProgrammeList title="次の予約" kind="reserves" :loading="loading" :error="errors.reserves" :enabled="enabled" :items="reserveItems" />
        <ProgrammeList title="最近の録画" kind="recordings" :loading="loading" :error="errors.recordings" :enabled="enabled" :items="recordingItems" />
      </div>
    </main>
    <footer class="station-footer"><nav aria-label="EDCB の画面"><a href="/E3/">EMWUI (E3) <span aria-hidden="true">↗</span></a><a href="/legacy/">EDCB 旧画面 (legacy) <span aria-hidden="true">↗</span></a></nav><p>最終更新 <time v-if="lastUpdated" :datetime="new Date(lastUpdated).toISOString()">{{ time(lastUpdated) }}</time><span v-else>未取得</span><span v-if="Object.values(errors).some(Boolean)">一部取得失敗</span></p></footer>
  </div>
</template>
