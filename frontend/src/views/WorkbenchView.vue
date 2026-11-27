<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 批次追溯链面板 -->
    <div v-if="showTrace && traceBatchNo" class="trace-panel">
      <h4>批次 {{ traceBatchNo }} 追溯链</h4>
      <div v-if="traceLoading">加载中...</div>
      <div v-else-if="traceError" class="error-text">{{ traceError }}</div>
      <div v-else class="trace-chain-inline">
        <div v-for="(node, idx) in traceChain" :key="idx" class="trace-node-inline"
          :class="{ frozen: node.frozen }">
          <div class="node-index">{{ idx + 1 }}</div>
          <div class="node-info">
            <strong>{{ getProcessName(node.module) }}</strong>
            <span>ID:{{ node.entry_id }}</span>
            <span class="node-status-tag" :class="node.status">{{ node.status }}</span>
          </div>
          <div v-if="node.data" class="node-meta">
            <span v-if="node.data['鲜叶重量'] || node.data['投入重量']">
              重量: {{ node.data['鲜叶重量'] || node.data['投入重量'] }}kg
            </span>
            <span v-if="node.data['产出重量']">→ 产出: {{ node.data['产出重量'] }}kg</span>
          </div>
          <div v-if="idx < traceChain.length - 1" class="trace-arrow">→</div>
        </div>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
        <tr :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-if="hasSupplements(row)"
              class="link supplement-link"
              type="button"
              :data-testid="`supplements-${row.id}`"
              @click="toggleSupplements(row)"
              title="查看补测受理详情">
              补测详情
            </button>
            <button
              v-if="row['批次号']"
              class="link trace-link"
              type="button"
              @click="viewBatchTrace(String(row['批次号']))"
              title="查看批次追溯">
              批次追溯
            </button>
            <button
              v-if="isProcessModule && row['上游记录ID']"
              class="link upstream-link"
              type="button"
              @click="viewUpstream(row)" title="查看上游工序">
              查看上游
            </button>
          </td>
        </tr>
        <tr v-if="expandedSupplementId === row.id" class="supplement-row">
          <td :colspan="meta.fields.length + 2">
            <div class="supplement-panel">
              <h5>核验单 {{ row['登记编号'] || row.id }} 补测受理情况（版本 V{{ row['核验单版本'] }}）</h5>
              <table class="supplement-table">
                <thead>
                  <tr>
                    <th>补测</th><th>来源</th><th>数值</th><th>签字人</th><th>设备编号</th>
                    <th>翻堆时段</th><th>状态</th><th>受理结论</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="sup in supplementsOf(row)" :key="String(sup['补测ID'])"
                      :class="{ accepted: sup['状态'] === '已受理', rejected: sup['状态'] === '不采用' }">
                    <td>#{{ sup['补测ID'] }}</td>
                    <td>{{ sup['来源'] }}</td>
                    <td>{{ sup['补测数值'] }}%</td>
                    <td>{{ sup['签字人'] || '—' }}</td>
                    <td>{{ sup['设备编号'] || '—' }}</td>
                    <td>{{ sup['翻堆时段'] || '—' }}</td>
                    <td>{{ sup['状态'] }}</td>
                    <td>{{ sup['受理结论'] || '—' }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="row.status === '已受理'" class="credential-line">
                转干燥凭据：{{ row['受理来源'] }} {{ row['受理数值'] }}%（受理时间 {{ row['受理时间'] || '—' }}），一堆茶只交接一次。
              </p>
              <p v-else class="credential-line pending">尚未形成转干燥凭据，干燥台领料将放入等待中。</p>
            </div>
          </td>
        </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" :required="isRequired(field)" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { fetchTraceChain } from '@/api/pipeline-client'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const router = useRouter()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

// 工序模块判断
const PROCESS_ORDER = ['picking', 'withering', 'fixing', 'rolling', 'fermentation', 'drying',
  'grading', 'blending', 'packing', 'trace_code', 'shipment']
const PROCESS_NAMES: Record<string, string> = {
  picking: '鲜叶采摘', withering: '萎凋', fixing: '杀青',
  rolling: '揉捻', fermentation: '发酵', drying: '干燥',
  grading: '精制分级', blending: '拼配', packing: '包装',
  trace_code: '溯源码段', shipment: '发运交接',
}
const isProcessModule = computed(() => PROCESS_ORDER.includes(meta.key))
// 批次追溯
const showTrace = ref(false)
const traceBatchNo = ref('')
const traceChain = ref<any[]>([])
const traceLoading = ref(false)
const traceError = ref('')

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function getProcessName(module: string): string {
  return PROCESS_NAMES[module] || module
}

function isRequired(field: string): boolean {
  return meta.requiredFields ? meta.requiredFields.includes(field) : true
}

// 缺测核验单：补测受理详情展开
const expandedSupplementId = ref<number | null>(null)

function supplementsOf(row: EntryRow): Array<Record<string, any>> {
  const list = row['补测列表']
  return Array.isArray(list) ? list : []
}

function hasSupplements(row: EntryRow): boolean {
  return supplementsOf(row).length > 0
}

function toggleSupplements(row: EntryRow) {
  expandedSupplementId.value = expandedSupplementId.value === Number(row.id) ? null : Number(row.id)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

async function viewBatchTrace(batchNo: string) {
  traceBatchNo.value = batchNo
  showTrace.value = true
  traceLoading.value = true
  traceError.value = ''
  try {
    const result = await fetchTraceChain(batchNo)
    traceChain.value = (result.chain || []).map((node: any) => ({
      ...node,
      frozen: false,
      status: node.data?.status || '',
    }))
  } catch (err: any) {
    traceError.value = err.message || '追溯链查询失败'
    traceChain.value = []
  } finally {
    traceLoading.value = false
  }
}

function viewUpstream(row: EntryRow) {
  const upstreamModule = row['上游工序']
  const upstreamId = row['上游记录ID']
  if (upstreamModule && upstreamId) {
    void router.push({ name: 'module', params: { moduleKey: String(upstreamModule) } })
  }
}

onMounted(reload)
</script>

<style scoped>
.trace-panel {
  margin-bottom: 12px;
  padding: 12px 16px;
  background: #f3f8ff;
  border-radius: 6px;
  border-left: 3px solid #3498db;
}
.trace-panel h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #2c3e50;
}
.trace-chain-inline {
  display: flex;
  align-items: flex-start;
  overflow-x: auto;
  gap: 4px;
  padding: 8px 0;
}
.trace-node-inline {
  flex: 0 0 auto;
  min-width: 130px;
  padding: 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid #ddd;
  font-size: 11px;
}
.trace-node-inline.frozen {
  border-color: #e74c3c;
  background: #fce4ec;
}
.node-index {
  width: 18px;
  height: 18px;
  background: #3498db;
  color: white;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  margin-right: 4px;
}
.node-info strong {
  display: block;
  font-size: 11px;
}
.node-info span {
  display: block;
  color: #7f8c8d;
  font-size: 10px;
}
.node-status-tag {
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 9px;
  display: inline-block;
}
.node-status-tag.已确认 { background: #d4edda; color: #155724; }
.node-status-tag.草稿 { background: #fff3cd; color: #856404; }
.node-status-tag.待确认 { background: #cce5ff; color: #004085; }
.node-status-tag.已撤回 { background: #f8d7da; color: #721c24; }
.node-meta {
  margin-top: 2px;
  font-size: 9px;
  color: #7f8c8d;
}
.trace-arrow {
  color: #3498db;
  font-size: 14px;
  margin: 0 2px;
  padding-top: 8px;
}
.trace-link, .upstream-link {
  color: #27ae60 !important;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 11px;
  border: 1px solid #27ae60;
  border-radius: 3px;
  text-decoration: none;
  cursor: pointer;
}
.trace-link:hover, .upstream-link:hover {
  background: #27ae60;
  color: white !important;
}
.supplement-link {
  color: #8e44ad !important;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 11px;
  border: 1px solid #8e44ad;
  border-radius: 3px;
  cursor: pointer;
}
.supplement-link:hover {
  background: #8e44ad;
  color: white !important;
}
.supplement-row td {
  background: #faf7fd;
  padding: 8px 12px;
}
.supplement-panel h5 {
  margin: 0 0 6px;
  font-size: 12px;
  color: #4a235a;
}
.supplement-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.supplement-table th, .supplement-table td {
  border: 1px solid #e2d9ec;
  padding: 3px 6px;
  text-align: left;
}
.supplement-table tr.accepted td {
  background: #d4edda;
}
.supplement-table tr.rejected td {
  color: #7f8c8d;
  background: #f4f4f4;
}
.credential-line {
  margin: 6px 0 0;
  font-size: 11px;
  color: #155724;
}
.credential-line.pending {
  color: #856404;
}
</style>