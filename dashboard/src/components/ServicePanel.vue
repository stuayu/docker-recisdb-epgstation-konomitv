<script setup lang="ts">
import { ref } from 'vue'
import type { ServiceConfig } from '../lib/config'
import type { ResolvedService } from '../lib/urls'
const props = defineProps<{ service: ServiceConfig; endpoints: ResolvedService; index: number; status: 'up' | 'down' | 'unknown' }>()
const copyState = ref('コピー')
const labels = { up: '稼働中', down: '応答なし', unknown: '未確認' }
async function copy() {
  try {
    if (!navigator.clipboard) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(props.service.local ?? '')
    copyState.value = 'コピー済み'
  } catch { copyState.value = '手動で選択・コピー' }
}
</script>

<template>
  <article class="service-panel" :class="{ 'service-panel--local': service.local }">
    <div class="service-panel__top">
      <span class="identity" :class="`identity--${index % 7}`" aria-hidden="true"></span>
      <span class="status-pill" :class="`status-pill--${status}`"><i aria-hidden="true"></i>{{ labels[status] }}</span>
    </div>
    <h3>{{ service.name }}</h3>
    <p class="service-panel__role">{{ service.role }}</p>
    <template v-if="service.local">
      <div class="local-address"><code tabindex="0">{{ service.local }}</code><button type="button" @click="copy" :aria-label="`${service.name} のアドレスをコピー`">{{ copyState }}</button></div>
      <p class="service-panel__note">{{ service.note }}</p>
      <span class="sr-only" role="status">{{ copyState === 'コピー' ? '' : copyState }}</span>
    </template>
    <div v-else class="service-panel__bottom">
      <div class="endpoint"><span class="endpoint__port">:{{ endpoints.primary?.port }}</span><span>{{ endpoints.primary?.protocol }}</span></div>
      <a v-if="endpoints.secondary" class="protocol-chip" :href="endpoints.secondary.url" :aria-label="`${service.name} を ${endpoints.secondary.protocol} で開く`">{{ endpoints.secondary.protocol }}</a>
      <a v-if="endpoints.primary" class="service-panel__open" :href="endpoints.primary.url" :aria-label="`${service.name} を開く`">開く <span aria-hidden="true">↗</span></a>
    </div>
  </article>
</template>
