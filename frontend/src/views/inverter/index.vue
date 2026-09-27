<template>
  <section class="page" data-module="inverter">
    <header class="page-head">
      <div>
        <h2>逆变器管理管理</h2>
        <p class="page-desc">维护逆变器，围绕逆变器编号、逆变器型号、额定功率、所属电站做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记逆变器</button>
        <button class="btn" type="button" @click="exportRows">导出逆变器管理清单</button>
      </div>
    </header>

    <section class="panel" data-block="ranking">
      <header class="panel-head">
        <h3>逆变器排行榜</h3>
        <label class="filter-item">
          <span>所属电站</span>
          <select v-model="activePlant" @change="switchPlant">
            <option value="">全部电站</option>
            <option v-for="plant in plants" :key="plant" :value="plant">{{ plant }}</option>
          </select>
        </label>
      </header>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in rankColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rankRows" :key="String(row['逆变器编号'])">
            <td>{{ index + 1 }}</td>
            <td>{{ row['逆变器编号'] }}</td>
            <td>{{ row['逆变器型号'] ?? '—' }}</td>
            <td>{{ row['所属电站'] ?? '—' }}</td>
            <td>{{ row['运行时长'] ?? '—' }}</td>
            <td>{{ row['告警次数'] ?? '—' }}</td>
            <td>{{ row['评分'] ?? '未评分' }}</td>
            <td>{{ row['评分时间'] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(String(row['逆变器编号']))">详情 / 评分</button>
            </td>
          </tr>
          <tr v-if="!rankRows.length">
            <td :colspan="rankColumns.length + 1" class="empty-state">当前电站暂无逆变器排行数据</td>
          </tr>
        </tbody>
      </table>

      <section v-if="detail" class="panel" data-block="detail">
        <header class="panel-head">
          <h3>逆变器详情 · {{ detail['逆变器编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">收起</button>
        </header>
        <div class="stat-row">
          <article v-for="item in detailItems" :key="item.label" class="stat-card">
            <span class="stat-label">{{ item.label }}</span>
            <strong class="stat-value">{{ item.value }}</strong>
          </article>
        </div>
        <form class="filter-bar" @submit.prevent="saveScore">
          <label class="filter-item">
            <span>评分（0-100）</span>
            <input v-model="scoreForm.score" type="number" min="0" max="100" step="0.1" required />
          </label>
          <label class="filter-item">
            <span>评分备注</span>
            <input v-model="scoreForm.remark" placeholder="选填" />
          </label>
          <button class="btn primary" type="submit">保存评分</button>
          <span v-if="scoreMessage" class="error-text">{{ scoreMessage }}</span>
        </form>
      </section>
    </section>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
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
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无逆变器管理数据，可先登记逆变器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条逆变器管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/inverter'
const columns = ["逆变器编号", "逆变器型号", "额定功率", "所属电站", "投产日期", "运行时长", "告警次数", "运行状态"]
const actions = ["停机检查", "复位告警", "恢复运行"]
const statuses = ["运行", "待机", "告警", "停机", "维修中"]
const stats = [{"label": "运行中逆变器", "value": 0}, {"label": "告警逆变器", "value": 0}, {"label": "停机逆变器", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 排行榜、详情、评分都按逆变器编号取数，不再各自维护一套设备关联。
const rankColumns = ["排名", "逆变器编号", "逆变器型号", "所属电站", "运行时长", "告警次数", "评分", "评分时间"]
const plants = ref<string[]>([])
const activePlant = ref('')
const rankRows = ref<Row[]>([])
const detail = ref<Row | null>(null)
const scoreForm = ref({ score: '', remark: '' })
const scoreMessage = ref('')

const detailItems = computed(() => {
  if (!detail.value) {
    return []
  }
  const source = detail.value
  return [
    { label: '逆变器编号', value: source['逆变器编号'] ?? '—' },
    { label: '逆变器型号', value: source['逆变器型号'] ?? '—' },
    { label: '所属电站', value: source['所属电站'] ?? '—' },
    { label: '运行时长', value: source['运行时长'] ?? '—' },
    { label: '告警次数', value: source['告警次数'] ?? '—' },
    { label: '当前评分', value: source['评分'] ?? '未评分' },
    { label: '评分时间', value: source['评分时间'] ?? '—' },
  ]
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '逆变器登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('逆变器管理动作未生效，请稍后重试')
    }
    await reload()
    await reloadRanking()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('逆变器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器管理列表读取失败'
  }
}

function switchPlant() {
  // 切换电站时先清空旧排行与详情，再按新电站拉取，避免上一电站的评分残留。
  rankRows.value = []
  detail.value = null
  scoreMessage.value = ''
  void reloadRanking()
}

async function reloadPlants() {
  try {
    const response = await request(`${ENDPOINT}/plants`)
    if (!response.ok) {
      throw new Error('电站列表读取失败')
    }
    const payload = await response.json()
    plants.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电站列表读取失败'
  }
}

async function reloadRanking() {
  errorMessage.value = ''
  const query = activePlant.value ? `?plant=${encodeURIComponent(activePlant.value)}` : ''
  try {
    const response = await request(`${ENDPOINT}/ranking${query}`)
    if (!response.ok) {
      throw new Error('逆变器排行榜读取失败')
    }
    const payload = await response.json()
    rankRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逆变器排行榜读取失败'
  }
}

async function openDetail(deviceNo: string) {
  scoreMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/ranking/${encodeURIComponent(deviceNo)}`)
    if (!response.ok) {
      throw new Error('逆变器详情读取失败')
    }
    detail.value = await response.json()
    scoreForm.value = {
      score: detail.value?.['评分'] != null ? String(detail.value['评分']) : '',
      remark: '',
    }
  } catch (error) {
    scoreMessage.value = error instanceof Error ? error.message : '逆变器详情读取失败'
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
  scoreMessage.value = ''
  const deviceNo = String(detail.value['逆变器编号'])
  try {
    const response = await request(`${ENDPOINT}/ranking/${encodeURIComponent(deviceNo)}/score`, {
      method: 'POST',
      body: JSON.stringify({
        values: { score: Number(scoreForm.value.score), remark: scoreForm.value.remark },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '评分保存失败')
    }
    // 读回结果直接来自服务端同一份数据，排行与详情保持一致。
    detail.value = payload.entry
    scoreForm.value = {
      score: payload.entry?.['评分'] != null ? String(payload.entry['评分']) : '',
      remark: '',
    }
    await reloadRanking()
  } catch (error) {
    scoreMessage.value = error instanceof Error ? error.message : '评分保存失败'
  }
}

onMounted(() => {
  void reload()
  void reloadPlants()
  void reloadRanking()
})
</script>

<style scoped>
.panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  background: #fff;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
}
</style>
