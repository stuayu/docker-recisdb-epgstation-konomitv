<script setup lang="ts">
import { duration, shortDate, time } from '../lib/format'
defineProps<{
  title: string
  kind: 'reserves' | 'recordings'
  loading: boolean
  error: string
  enabled: boolean
  items: { id: number; title: string; startTime: string; durationSecond: number; station: string; recording?: boolean }[]
}>()
</script>

<template>
  <section class="programme-panel" :aria-label="title">
    <div class="section-heading"><h2>{{ title }}</h2><a :href="kind === 'reserves' ? '/E3/#epg' : '/E3/#recinfo'">{{ kind === 'reserves' ? '番組表へ' : '録画一覧へ' }} <span aria-hidden="true">↗</span></a></div>
    <p v-if="!enabled" class="empty-state">EDCB の情報表示は無効です。<a href="/E3/">EMWUI を開く</a></p>
    <p v-else-if="loading" class="empty-state" role="status">{{ title }}を読み込んでいます…</p>
    <p v-else-if="error" class="empty-state" role="status">{{ kind === 'reserves' ? '予約' : '録画履歴' }}を取得できません。<a href="/E3/">EMWUI で確認する</a></p>
    <ol v-else-if="items.length" class="programme-list">
      <li v-for="item in items" :key="item.id" :class="{ 'programme-row--rec': item.recording }">
        <div class="programme-time"><span>{{ shortDate(item.startTime) }}</span><time :datetime="item.startTime">{{ time(item.startTime) }}</time></div>
        <div class="programme-detail"><span v-if="item.recording" class="rec-label"><i aria-hidden="true"></i>録画中</span><h3 :title="item.title">{{ item.title }}</h3><p><span>{{ item.station }}</span><span>{{ duration(item.durationSecond) }}</span></p></div>
      </li>
    </ol>
    <p v-else class="empty-state">{{ kind === 'reserves' ? '予約はまだありません。番組表から予約できます。' : '録画履歴はまだありません。録画が終わると、ここに表示されます。' }}<a href="/E3/">{{ kind === 'reserves' ? '番組表を開く' : 'EMWUI を開く' }}</a></p>
  </section>
</template>
