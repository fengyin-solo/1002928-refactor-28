<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.title }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">{{ meta.primaryText }}</button>
        <button class="btn" type="button" @click="exportRows">{{ meta.exportText }}</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="card in metricCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length && !listError">
          <td :colspan="meta.fields.length + 1" class="empty-state">{{ meta.emptyText }}</td>
        </tr>
        <tr v-if="listError">
          <td :colspan="meta.fields.length + 1" class="empty-state">
            {{ listError }}
            <button class="link" type="button" @click="reload">重试</button>
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.recordNoun }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'
import type { ModuleMeta } from '@/modules'

const props = defineProps<{ meta: ModuleMeta }>()
const meta = computed(() => props.meta)
const endpoint = computed(() => `/api/${meta.value.key}`)

type Row = Record<string, string | number | boolean | null>
type Metrics = { created: number; pending: number; abnormal: number }
type PagePayload = { items?: Row[]; total?: number }

const rows = ref<Row[]>([])
const total = ref(0)
const metricsData = ref<Metrics>({ created: 0, pending: 0, abnormal: 0 })
const listError = ref('')
const metricsError = ref('')
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

const filterFields = computed(() => meta.value.fields.slice(0, 3))
const metricCards = computed(() => [
  { label: '今日新增', value: metricsData.value.created },
  { label: '待处理', value: metricsData.value.pending },
  { label: '异常量', value: metricsData.value.abnormal },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${endpoint.value}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = meta.value.createHint
}

// 指标与列表分开取数：指标走 /metrics，与首页 /api/overview 同源同口径。
async function loadMetrics() {
  metricsError.value = ''
  try {
    const payload = await fetchJson<Metrics>(`${endpoint.value}/metrics`)
    metricsData.value = {
      created: payload.created ?? 0,
      pending: payload.pending ?? 0,
      abnormal: payload.abnormal ?? 0,
    }
  } catch (error) {
    metricsError.value = error instanceof Error ? error.message : '指标读取失败'
    errorMessage.value = metricsError.value
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${endpoint.value}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(meta.value.actionFail)
    }
    await Promise.all([reload(), loadMetrics()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : meta.value.listFail
  }
}

// fetchJson 已对网络错误 / 5xx 自动重试；仍失败时页内提供「重试」按钮。
async function reload() {
  listError.value = ''
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const payload = await fetchJson<PagePayload>(`${endpoint.value}?${query}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadMetrics()
  } catch (error) {
    listError.value = error instanceof Error ? error.message : meta.value.listThrow
    errorMessage.value = listError.value
  }
}

onMounted(reload)
</script>
