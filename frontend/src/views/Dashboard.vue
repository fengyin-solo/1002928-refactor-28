<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。卡片与明细同源同口径。</p>
      </div>
      <div class="page-actions">
        <label class="filter-item">
          <span>看板版本</span>
          <select :value="activeVersion" @change="switchVersion(($event.target as HTMLSelectElement).value)">
            <option v-for="snap in snapshots" :key="snap.version" :value="snap.version">
              {{ snap.version }} · {{ snap.label }}
            </option>
          </select>
        </label>
        <button class="btn" type="button" :disabled="loading" @click="loadOverview">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
    </header>

    <div v-if="loadError" class="filter-bar">
      <span class="error-text">{{ loadError }}</span>
      <button class="btn" type="button" @click="loadOverview">重试</button>
    </div>

    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <p class="page-desc">当前版本：{{ activeVersion }}<span v-if="versionLabel"> · {{ versionLabel }}</span></p>

    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.label ?? row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>

    <section class="filter-bar" style="margin-top: 16px; display: block;">
      <h3 style="margin: 0 0 8px;">批次汇总（幂等提交演示）</h3>
      <p class="page-desc" style="margin: 0 0 8px;">
        同一 batch_id 重复提交只落一次账；按钮连点两次可验证台数不会叠成两份。
      </p>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="submitDemoBatch(false)">提交一批明细</button>
        <button class="btn" type="button" @click="submitDemoBatch(true)">用同一 batch_id 再提交</button>
      </div>
      <p v-if="batchMessage" class="page-desc" style="margin-top: 8px;">{{ batchMessage }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, postJson } from '@/api/client'
import { MODULES } from '@/modules'

type Cards = { label: string; value: number }[]
type ModuleRow = { name: string; label?: string; created: number; pending: number; abnormal: number }
type Overview = { version?: string; cards: Cards; modules: ModuleRow[] }
type Snapshot = { version: string; label: string; as_of: string; overview: Overview }

const emptyOverview: Overview = {
  cards: [
    { label: '业务模块', value: 0 },
    { label: '今日新增', value: 0 },
    { label: '待处理', value: 0 },
    { label: '异常量', value: 0 },
  ],
  modules: [],
}

const cards = ref<Cards>(emptyOverview.cards)
const moduleRows = ref<ModuleRow[]>([])
const snapshots = ref<Snapshot[]>([])
const activeVersion = ref('')
const loading = ref(false)
const loadError = ref('')
const batchMessage = ref('')

const labelByName = new Map(MODULES.map((item) => [item.key, item.title.replace(/管理$/, '')]))
const versionLabel = computed(
  () => snapshots.value.find((item) => item.version === activeVersion.value)?.label ?? '',
)

function applyOverview(overview: Overview) {
  cards.value = overview.cards
  moduleRows.value = overview.modules.map((row) => ({
    ...row,
    label: labelByName.get(row.name) ?? row.name,
  }))
}

async function loadOverview() {
  loading.value = true
  loadError.value = ''
  try {
    const [overview, snapshotPayload] = await Promise.all([
      fetchJson<Overview>('/api/overview'),
      fetchJson<{ current: string; snapshots: Snapshot[] }>('/api/overview/snapshots'),
    ])
    snapshots.value = snapshotPayload.snapshots
    if (!activeVersion.value || activeVersion.value === overview.version) {
      activeVersion.value = overview.version ?? snapshotPayload.current
      applyOverview(overview)
    }
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '运营概览读取失败'
  } finally {
    loading.value = false
  }
}

async function switchVersion(version: string) {
  activeVersion.value = version
  loadError.value = ''
  try {
    const snap = await fetchJson<Snapshot>(`/api/overview/snapshots/${version}`)
    applyOverview(snap.overview)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '历史看板读取失败'
  }
}

const demoBatchId = 'demo-batch-0001'
async function submitDemoBatch(repeat: boolean) {
  batchMessage.value = ''
  const payload = {
    batch_id: demoBatchId,
    entries: [
      { module: 'boiler', id: 1 },
      { module: 'boiler', id: 2 },
      { module: 'register', id: 1 },
      { module: 'hazard', id: 2 },
    ],
  }
  try {
    const result = await postJson<{
      deduplicated: boolean
      totals: Record<string, number>
    }>('/api/batches', payload)
    const { created, pending, abnormal, units } = result.totals
    batchMessage.value = result.deduplicated
      ? `检测到 batch_id=${demoBatchId} 已提交过，直接回放：台数仍为 ${units}（新增 ${created}/待处理 ${pending}/异常 ${abnormal}），没有叠加。`
      : `批次${repeat ? '（重复提交）' : ''}已落账：台数 ${units}（新增 ${created}/待处理 ${pending}/异常 ${abnormal}）。`
  } catch (error) {
    batchMessage.value = error instanceof Error ? error.message : '批次提交失败，请重试'
  }
}

onMounted(loadOverview)
</script>
