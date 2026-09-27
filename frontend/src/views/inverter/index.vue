<template>
  <section class="page" data-module="inverter">
    <header class="page-head">
      <div>
        <h2>逆变器排行榜</h2>
        <p class="page-desc">排行、详情与评分保存按逆变器编号关联同一份设备数据；切换电站不会残留上一座电站的评分。</p>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="filter-bar">
      <label class="filter-item">
        <span>所属电站</span>
        <select v-model="station" class="station-select" @change="switchStation">
          <option value="">全部电站</option>
          <option v-for="name in stations" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <button class="btn ghost" type="button" @click="reload(true)">刷新排行</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>名次</th>
          <th>逆变器编号</th>
          <th>逆变器型号</th>
          <th>所属电站</th>
          <th>运行时长(h)</th>
          <th>告警次数</th>
          <th>运行状态</th>
          <th>评分</th>
          <th>评语</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.逆变器编号"
          :class="{ 'row-active': detail?.逆变器编号 === row.逆变器编号 }"
        >
          <td>{{ row.名次 }}</td>
          <td>{{ row.逆变器编号 }}</td>
          <td>{{ row.逆变器型号 }}</td>
          <td>{{ row.所属电站 }}</td>
          <td>{{ row.运行时长 }}</td>
          <td>{{ row.告警次数 }}</td>
          <td>{{ row.运行状态 }}</td>
          <td>{{ row.评分 ?? '未评分' }}</td>
          <td>{{ row.评语 || '—' }}</td>
          <td>
            <button class="link" type="button" @click="openDetail(row.逆变器编号)">详情 / 评分</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="10" class="empty-state">当前电站暂无逆变器数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ rows.length }} 台设备</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <aside v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>设备详情 · {{ detail.逆变器编号 }}</h3>
        <button class="link" type="button" @click="closeDetail">关闭</button>
      </header>
      <dl class="detail-grid">
        <div><dt>逆变器型号</dt><dd>{{ detail.逆变器型号 }}</dd></div>
        <div><dt>额定功率</dt><dd>{{ detail.额定功率 }}</dd></div>
        <div><dt>所属电站</dt><dd>{{ detail.所属电站 }}</dd></div>
        <div><dt>投产日期</dt><dd>{{ detail.投产日期 }}</dd></div>
        <div><dt>运行时长(h)</dt><dd>{{ detail.运行时长 }}</dd></div>
        <div><dt>告警次数</dt><dd>{{ detail.告警次数 }}</dd></div>
        <div><dt>运行状态</dt><dd>{{ detail.运行状态 }}</dd></div>
        <div>
          <dt>当前评分</dt>
          <dd>
            {{ detail.评分 ?? '未评分' }}
            <span v-if="detail.评分时间" class="score-meta">{{ detail.评分人 }} · {{ detail.评分时间 }}</span>
          </dd>
        </div>
      </dl>
      <form class="score-form" @submit.prevent="saveScore">
        <label class="filter-item">
          <span>评分（0-100）</span>
          <input v-model.number="scoreForm.评分" type="number" min="0" max="100" step="0.5" placeholder="输入评分" />
        </label>
        <label class="filter-item">
          <span>评语</span>
          <input v-model="scoreForm.评语" placeholder="选填" />
        </label>
        <button class="btn primary" type="submit">保存评分</button>
        <span v-if="scoreMessage" class="score-meta">{{ scoreMessage }}</span>
      </form>
    </aside>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type RankingRow = {
  名次: number
  逆变器编号: string
  逆变器型号: string
  所属电站: string
  运行时长: number
  告警次数: number
  运行状态: string
  评分: number | null
  评语: string | null
  评分人: string | null
  评分时间: string | null
}

type DeviceDetail = RankingRow & {
  id: number
  额定功率: string
  投产日期: string
}

type RankingResponse = {
  station: string
  stations: string[]
  items: RankingRow[]
  total: number
}

const session = useSessionStore()

const station = ref('')
const stations = ref<string[]>([])
const rows = ref<RankingRow[]>([])
const detail = ref<DeviceDetail | null>(null)
const errorMessage = ref('')
const scoreMessage = ref('')
const scoreForm = reactive({ 评分: null as number | null, 评语: '' })

// 排行缓存：按电站分键，切换电站只读本电站的缓存；
// 评分保存后整体清空，重新进入页面时也会重新拉取，不会残留旧评分。
const rankingCache = new Map<string, RankingRow[]>()

const stats = computed(() => {
  const scored = rows.value.filter((row) => row.评分 !== null)
  const average = scored.length
    ? (scored.reduce((sum, row) => sum + Number(row.评分), 0) / scored.length).toFixed(1)
    : '—'
  return [
    { label: '排行设备', value: rows.value.length },
    { label: '已评分设备', value: scored.length },
    { label: '平均评分', value: average },
  ]
})

async function reload(fresh = false) {
  errorMessage.value = ''
  const key = station.value
  if (!fresh && rankingCache.has(key)) {
    rows.value = rankingCache.get(key) ?? []
    return
  }
  try {
    const query = key ? `?station=${encodeURIComponent(key)}` : ''
    const payload = await fetchJson<RankingResponse>(`/api/inverter/ranking${query}`)
    stations.value = payload.stations ?? []
    rows.value = payload.items ?? []
    rankingCache.set(key, rows.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器排行榜读取失败'
  }
}

function switchStation() {
  closeDetail() // 切换电站后详情面板一并收起，避免带出上一座电站的设备
  void reload()
}

async function openDetail(code: string) {
  errorMessage.value = ''
  scoreMessage.value = ''
  try {
    const payload = await fetchJson<DeviceDetail>(`/api/inverter/device/${encodeURIComponent(code)}`)
    detail.value = payload
    scoreForm.评分 = payload.评分
    scoreForm.评语 = payload.评语 ?? ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  scoreMessage.value = ''
}

async function saveScore() {
  if (!detail.value) {
    return
  }
  errorMessage.value = ''
  scoreMessage.value = ''
  const code = detail.value.逆变器编号
  try {
    const response = await request('/api/inverter/score', {
      method: 'POST',
      body: JSON.stringify({
        values: {
          逆变器编号: code,
          评分: scoreForm.评分,
          评语: scoreForm.评语,
          评分人: session.operator,
        },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '评分保存未生效，请稍后重试')
    }
    // 保存成功：详情直接展示后端读回的最新评分，排行缓存失效后重新拉取
    detail.value = payload.entry
    scoreForm.评分 = payload.entry.评分
    scoreForm.评语 = payload.entry.评语 ?? ''
    scoreMessage.value = payload.message
    rankingCache.clear()
    await reload(true)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '评分保存失败'
  }
}

onMounted(() => reload(true))
</script>

<style scoped>
.station-select {
  min-width: 160px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
}
.row-active td {
  background: #eef4ff;
}
.detail-panel {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-head h3 {
  margin: 0;
  font-size: 15px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px 16px;
  margin: 12px 0;
}
.detail-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.detail-grid dd {
  margin: 2px 0 0;
  font-size: 13px;
}
.score-form {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.score-meta {
  font-size: 12px;
  color: var(--muted);
  margin-left: 6px;
}
</style>
