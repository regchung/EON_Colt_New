<script setup>
import { onMounted, ref, reactive, computed, watch } from 'vue'
import { useOrdersStore } from '../stores/orders'
import { useVehiclesStore } from '../stores/vehicles'
import client from '../api/client'
import SuggestVehicle from '../components/SuggestVehicle.vue'
import Pagination from '../components/Pagination.vue'

const store = useOrdersStore()
const vehiclesStore = useVehiclesStore()
const vehicleMap = computed(() =>
  Object.fromEntries(vehiclesStore.items.map((v) => [v.id, v]))
)
function vehicleLabel(id) {
  const v = vehicleMap.value[id]
  return v ? v.plate || `車#${v.id}` : `車#${id}`
}
function fmtEta(eta) {
  return eta ? eta.slice(11, 16) : ''
}


// --- 大豐班表 Excel 匯入 ---
const daifongFileInput = ref(null)
const daifongImporting = ref(false)
const daifongReport = ref(null)

function pickDaifongFile() {
  daifongReport.value = null
  daifongFileInput.value?.click()
}

async function onDaifongFileChosen(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const replace = confirm(`匯入大豐班表「${file.name}」?\n\n選「確定」= 取代同日期既有訂單\n選「取消」= 僅新增(不刪既有)`)
  daifongImporting.value = true
  daifongReport.value = null
  try {
    const fd = new FormData()
    fd.append('file', file)
    const { data } = await client.post('/orders/import-daifong', fd, {
      params: { replace_date: replace },
      timeout: 300000,
    })
    daifongReport.value = data
    await store.fetchAll()
  } catch (err) {
    daifongReport.value = { error: err?.response?.data?.detail || err.message || '匯入失敗' }
  } finally {
    daifongImporting.value = false
    e.target.value = ''
  }
}


// --- 地理編碼 ---
const geocoding = ref(false)
const geocodeReport = ref(null)

async function runGeocode() {
  geocoding.value = true
  geocodeReport.value = null
  try {
    const { data } = await client.post('/orders/geocode-pending')
    geocodeReport.value = data
    await store.fetchAll()
  } catch (err) {
    geocodeReport.value = { error: err?.response?.data?.detail || err.message }
  } finally {
    geocoding.value = false
  }
}

function hasCoords(o) {
  return o.pickup_lng != null && o.dropoff_lng != null
}

// --- 一鍵排班 ---
const dispatching = ref(false)
const dispatchReport = ref(null)

async function runDispatch() {
  if (!filters.service_date) {
    alert('請先在上方篩選列選擇「服務日期」再執行排班')
    return
  }
  const sd = filters.service_date
  const confirmed = confirm(
    `⚠️ 一鍵排班：${sd}\n\n` +
    `執行前將清除該日所有派遣相關資料（指派車輛、路線停靠點、比較記錄），並重新自動排班。\n\n` +
    `確定要繼續嗎？`
  )
  if (!confirmed) return
  dispatching.value = true
  dispatchReport.value = null
  try {
    // ① 執行排班（寫入 orders + route_stop）
    const { data } = await client.post('/dispatch/run', null, { params: { service_date: sd } })
    dispatchReport.value = data
    // ② 自動落地到 auto_dispatch_stop（source=run：從已派結果同步，不重跑 VROOM）
    await client.post('/dispatch/comparison/persist-day', null,
      { params: { service_date: sd, source: 'run' } }).catch(() => {})
    await store.fetchAll(filters.service_date ? { service_date: sd } : {})
  } catch (err) {
    dispatchReport.value = { error: err?.response?.data?.detail || err.message }
  } finally {
    dispatching.value = false
  }
}

const STATUS = {
  imported: '已匯入',
  scheduled: '已排班',
  ongoing: '進行中',
  done: '已完成',
  canceled: '已取消',
}

const filters = reactive({ service_date: '', status: '', vehicle_type: '' })

// 分頁
const PAGE_SIZE = 50
const currentPage = ref(1)
const pagedOrders = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return store.items.slice(start, start + PAGE_SIZE)
})
watch(() => store.items, () => { currentPage.value = 1 })

const blank = () => ({
  service_date: new Date().toISOString().slice(0, 10),
  pickup_time: new Date().toISOString().slice(0, 16),
  pickup_window_min: 30,
  passenger_name: '',
  passenger_phone: '',
  pickup_address: '',
  dropoff_address: '',
  pax: 1,
  vehicle_type: 'normal',
  need_wheelchair: false,
  allow_pool: false,   // 原則不共乘
  note: '',
  payment_type: '',
  order_nature: '',
  customer_region: '',
  eligibility: '',
  status: 'imported',
})

const showForm = ref(false)
const editingId = ref(null)
const form = reactive(blank())

onMounted(() => {
  store.fetchAll()
  vehiclesStore.fetchAll()
})

function applyFilters() {
  const params = {}
  if (filters.service_date) params.service_date = filters.service_date
  if (filters.status) params.status = filters.status
  if (filters.vehicle_type) params.vehicle_type = filters.vehicle_type
  store.fetchAll(params)
}

function openCreate() {
  Object.assign(form, blank())
  editingId.value = null
  showForm.value = true
}
function openEdit(o) {
  Object.assign(form, {
    ...o,
    pickup_time: (o.pickup_time || '').slice(0, 16),
  })
  editingId.value = o.id
  showForm.value = true
}
async function save() {
  const payload = { ...form, pickup_time: new Date(form.pickup_time).toISOString() }
  if (editingId.value) await store.update(editingId.value, payload)
  else await store.create(payload)
  showForm.value = false
}
async function remove(o) {
  if (confirm(`確定刪除訂單 #${o.id}?`)) await store.remove(o.id)
}

async function cancelOrder(o) {
  if (!confirm(`確定取消訂單 #${o.id}?(下次排班會自動排除)`)) return
  await client.post(`/orders/${o.id}/cancel`)
  await store.fetchAll(filters.service_date ? { service_date: filters.service_date } : {})
}
async function setStatus(o, value) {
  await client.post(`/orders/${o.id}/status`, null, { params: { value } })
  await store.fetchAll(filters.service_date ? { service_date: filters.service_date } : {})
}

// --- 區域親和建議 ---
const zoneSuggest = ref(null)   // { order, data, loading }
async function suggestZone(o) {
  zoneSuggest.value = { order: o, data: null, loading: true }
  try {
    const { data } = await client.post('/dispatch/zone-suggest', null, {
      params: { order_id: o.id, service_date: o.service_date },
    })
    zoneSuggest.value = { order: o, data, loading: false }
  } catch (err) {
    zoneSuggest.value = { order: o, data: { error: err?.response?.data?.detail || err.message }, loading: false }
  }
}
async function adoptVehicle(orderId, vehicleId) {
  await client.post(`/orders/${orderId}/assign`, null, { params: { vehicle_id: vehicleId } })
  zoneSuggest.value = null
  await store.fetchAll(filters.service_date ? { service_date: filters.service_date } : {})
}

// --- 最佳車輛建議(插入成本 + 切換車隊)---
const suggestVehOrder = ref(null)
function openSuggestVeh(o) {
  suggestVehOrder.value = {
    id: o.id, fleet: o.fleet, passenger: o.passenger_name,
    pickup: o.pickup_address, dropoff: o.dropoff_address,
    welfare: o.vehicle_type === 'welfare' || o.need_wheelchair,
    time: (o.pickup_time || '').slice(11, 16),
  }
}
async function onVehAssigned() {
  suggestVehOrder.value = null
  await store.fetchAll(filters.service_date ? { service_date: filters.service_date } : {})
}
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <span class="text-muted">共 {{ store.items.length }} 筆</span>
    <div class="btn-group flex-wrap">
      <button class="btn btn-success" :disabled="daifongImporting" @click="pickDaifongFile"
              title="匯入大豐派遣班表 Excel(民國日期格式)">
        {{ daifongImporting ? '大豐匯入中…' : '📥 大豐匯入' }}
      </button>
      <button class="btn btn-outline-info" :disabled="geocoding" @click="runGeocode">
        {{ geocoding ? '編碼中…' : '地理編碼待處理' }}
      </button>
      <button class="btn btn-warning" :disabled="dispatching" @click="runDispatch">
        {{ dispatching ? '排班中…' : '🚀 一鍵排班' }}
      </button>
      <button class="btn btn-primary" @click="openCreate">+ 新增訂單</button>
    </div>
    <input
      ref="daifongFileInput"
      type="file"
      accept=".xlsx,.xls"
      class="d-none"
      @change="onDaifongFileChosen"
    />
  </div>

  <!-- 大豐匯入報告 -->
  <div v-if="daifongImporting" class="alert alert-success py-2">📥 大豐班表匯入中，請稍候…</div>
  <div v-else-if="daifongReport" class="card border-success mb-3">
    <div class="card-header d-flex justify-content-between align-items-center bg-success text-white">
      <span>📥 大豐班表匯入結果</span>
      <button type="button" class="btn-close btn-close-white" @click="daifongReport = null"></button>
    </div>
    <div class="card-body">
      <template v-if="daifongReport.error">
        <span class="text-danger">匯入失敗：{{ daifongReport.error }}</span>
      </template>
      <template v-else>
        <strong>匯入完成</strong>：共 <b>{{ daifongReport.imported }}</b> 筆，
        略過 {{ daifongReport.skipped }} 筆，
        涵蓋 {{ daifongReport.date_count }} 個服務日期
        ({{ (daifongReport.dates || [])[0] }} ~ {{ (daifongReport.dates || []).slice(-1)[0] }})。
        <div v-if="daifongReport.errors?.length" class="mt-2 small text-danger">
          錯誤(前{{ daifongReport.errors.length }}筆)：
          <ul class="mb-0">
            <li v-for="e in daifongReport.errors" :key="e">{{ e }}</li>
          </ul>
        </div>
      </template>
    </div>
  </div>

  <!-- 地理編碼報告 -->
  <div v-if="geocodeReport" class="alert" :class="geocodeReport.error ? 'alert-danger' : 'alert-info'">
    <template v-if="geocodeReport.error">地理編碼失敗:{{ geocodeReport.error }}</template>
    <template v-else>
      <strong>地理編碼完成</strong>:處理 {{ geocodeReport.processed }} 筆,
      成功 <span class="text-success fw-bold">{{ geocodeReport.succeeded }}</span> 筆,
      失敗 <span class="text-danger fw-bold">{{ geocodeReport.failed }}</span> 筆。
      <span v-if="geocodeReport.processed === 0" class="text-muted">(沒有待處理的訂單)</span>
    </template>
    <button type="button" class="btn-close float-end" @click="geocodeReport = null"></button>
  </div>

  <!-- 排班結果 -->
  <div v-if="dispatchReport" class="card border-warning mb-3">
    <div class="card-header bg-warning-subtle d-flex justify-content-between align-items-center">
      <strong>🚀 排班結果</strong>
      <button type="button" class="btn-close" @click="dispatchReport = null"></button>
    </div>
    <div class="card-body">
      <template v-if="dispatchReport.error">
        <div class="text-danger">排班失敗:{{ dispatchReport.error }}</div>
      </template>
      <template v-else>
        <p class="mb-2">
          用車 <strong>{{ dispatchReport.vehicles_used }}</strong> 台,
          已派 <span class="text-success fw-bold">{{ dispatchReport.assigned }}</span> /
          {{ dispatchReport.orders_total }} 筆,
          未派 <span class="text-danger fw-bold">{{ dispatchReport.unassigned?.length || 0 }}</span> 筆,
          矩陣來源 <span class="badge bg-secondary">{{ dispatchReport.provider }}</span>,
          總行駛 {{ Math.round((dispatchReport.total_duration_sec || 0) / 60) }} 分。
        </p>
        <div v-if="dispatchReport.unassigned?.length" class="alert alert-warning py-1 px-2 small">
          未派訂單(可能超出班別/座位/時間窗):#{{ dispatchReport.unassigned.join(', #') }}
        </div>
        <div v-if="dispatchReport.ai_summary" class="alert alert-info small mb-2" style="white-space:pre-wrap">
          🤖 <strong>AI 分析</strong><br>{{ dispatchReport.ai_summary }}
        </div>
        <div class="row g-3">
          <div v-for="(stops, vid) in dispatchReport.routes" :key="vid" class="col-12 col-lg-6">
            <div class="border rounded p-2 h-100">
              <div class="fw-bold mb-2">
                {{ vehicleLabel(Number(vid)) }}
                <span class="badge" :class="vehicleMap[vid]?.type === 'welfare' ? 'bg-warning text-dark' : 'bg-secondary'">
                  {{ vehicleMap[vid]?.type === 'welfare' ? '福祉車' : '一般車' }}
                </span>
              </div>
              <ol class="list-group list-group-flush small">
                <li v-for="(s, i) in stops" :key="i" class="list-group-item px-1 py-1 d-flex justify-content-between">
                  <span>
                    <span :class="s.type === '上車' ? 'text-success' : 'text-primary'">{{ s.type }}</span>
                    #{{ s.order_id }} · {{ s.addr }}
                  </span>
                  <span class="text-muted text-nowrap ms-2">{{ s.eta }}</span>
                </li>
              </ol>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>

  <!-- 篩選列 -->
  <div class="card card-body bg-light mb-3">
    <div class="row g-2 align-items-end">
      <div class="col-6 col-md-3">
        <label class="form-label mb-1 small">服務日期</label>
        <input v-model="filters.service_date" type="date" class="form-control form-control-sm" />
      </div>
      <div class="col-6 col-md-3">
        <label class="form-label mb-1 small">狀態</label>
        <select v-model="filters.status" class="form-select form-select-sm">
          <option value="">全部</option>
          <option v-for="(label, key) in STATUS" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>
      <div class="col-6 col-md-3">
        <label class="form-label mb-1 small">車種</label>
        <select v-model="filters.vehicle_type" class="form-select form-select-sm">
          <option value="">全部</option>
          <option value="normal">一般車</option>
          <option value="welfare">福祉車</option>
        </select>
      </div>
      <div class="col-6 col-md-3">
        <button class="btn btn-sm btn-outline-primary w-100" @click="applyFilters">套用篩選</button>
      </div>
    </div>
  </div>

  <div v-if="store.error" class="alert alert-danger">{{ store.error }}</div>

  <!-- 表單 -->
  <div v-if="showForm" class="card shadow-sm mb-3">
    <div class="card-header">{{ editingId ? '編輯訂單' : '新增訂單' }}</div>
    <div class="card-body">
      <div class="row g-3">
        <div class="col-6 col-md-3">
          <label class="form-label">服務日期 *</label>
          <input v-model="form.service_date" type="date" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">預約上車時間 *</label>
          <input v-model="form.pickup_time" type="datetime-local" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">時間彈性(分)</label>
          <input v-model.number="form.pickup_window_min" type="number" min="0" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">人數</label>
          <input v-model.number="form.pax" type="number" min="1" class="form-control" />
        </div>

        <div class="col-12 col-md-6">
          <label class="form-label">乘客姓名</label>
          <input v-model="form.passenger_name" class="form-control" />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">乘客電話</label>
          <input v-model="form.passenger_phone" class="form-control" />
        </div>

        <div class="col-12 col-md-6">
          <label class="form-label">上車地址 *</label>
          <input v-model="form.pickup_address" class="form-control" />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">下車地址 *</label>
          <input v-model="form.dropoff_address" class="form-control" />
        </div>

        <div class="col-6 col-md-3">
          <label class="form-label">車種</label>
          <select v-model="form.vehicle_type" class="form-select">
            <option value="normal">一般車</option>
            <option value="welfare">福祉車</option>
          </select>
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">狀態</label>
          <select v-model="form.status" class="form-select">
            <option v-for="(label, key) in STATUS" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
        <div class="col-12 col-md-6 d-flex align-items-end gap-4">
          <div class="form-check">
            <input v-model="form.need_wheelchair" class="form-check-input" type="checkbox" id="oWheel" />
            <label class="form-check-label" for="oWheel">需要輪椅</label>
          </div>
          <div class="form-check">
            <input v-model="form.allow_pool" class="form-check-input" type="checkbox" id="oPool" />
            <label class="form-check-label" for="oPool">可共乘</label>
          </div>
        </div>

        <div class="col-md-4">
          <label class="form-label">付款方式</label>
          <select v-model="form.payment_type" class="form-select">
            <option value="">—未設定—</option>
            <option value="subsidy">補助</option>
            <option value="self">自費</option>
          </select>
        </div>
        <div class="col-md-4">
          <label class="form-label">性質</label>
          <input v-model="form.order_nature" class="form-control" placeholder="例：就醫、洗腎、復健" />
        </div>
        <div class="col-md-4">
          <label class="form-label">客戶所在地區</label>
          <input v-model="form.customer_region" class="form-control" placeholder="例：信義區" />
        </div>
        <div class="col-md-4">
          <label class="form-label">身份資格</label>
          <select v-model="form.eligibility" class="form-select">
            <option value="">—未設定—</option>
            <option value="一般">一般</option>
            <option value="低收入戶">低收入戶</option>
            <option value="中低收9%">中低收9%</option>
            <option value="偏鄉低收2400">偏鄉低收2400</option>
          </select>
        </div>
        <div class="col-12">
          <label class="form-label">備註</label>
          <textarea v-model="form.note" class="form-control" rows="2"></textarea>
        </div>
      </div>
    </div>
    <div class="card-footer text-end">
      <button class="btn btn-secondary me-2" @click="showForm = false">取消</button>
      <button
        class="btn btn-primary"
        :disabled="!form.pickup_address || !form.dropoff_address"
        @click="save"
      >儲存</button>
    </div>
  </div>

  <!-- 區域親和建議 modal -->
  <div v-if="zoneSuggest" class="zone-overlay" @click.self="zoneSuggest = null">
    <div class="card shadow zone-card">
      <div class="card-header d-flex justify-content-between align-items-center">
        <strong>🧭 區域親和建議 — 訂單 #{{ zoneSuggest.order.id }}</strong>
        <button class="btn-close" @click="zoneSuggest = null"></button>
      </div>
      <div class="card-body">
        <div v-if="zoneSuggest.loading" class="text-muted">查詢中…</div>
        <div v-else-if="zoneSuggest.data?.error" class="alert alert-danger py-2">{{ zoneSuggest.data.error }}</div>
        <template v-else>
          <p class="mb-2">
            區域:<span class="badge bg-secondary">{{ zoneSuggest.data.zone || '未知' }}</span>
            <span v-if="zoneSuggest.data.affinity_triggered" class="badge bg-success ms-1">親和觸發</span>
            <span v-else class="badge bg-light text-dark ms-1">未觸發</span>
          </p>
          <div class="alert alert-info py-2 small">{{ zoneSuggest.data.explanation }}</div>
          <table class="table table-sm align-middle mb-2">
            <thead><tr><th>車輛</th><th>車種</th><th>該區</th><th>當日</th><th>可行</th><th></th></tr></thead>
            <tbody>
              <tr v-for="s in zoneSuggest.data.suggestions" :key="s.vehicle_id"
                  :class="{ 'table-success': zoneSuggest.data.recommended && s.vehicle_id === zoneSuggest.data.recommended.vehicle_id }">
                <td>{{ s.plate }}</td>
                <td>{{ s.type === 'welfare' ? '福祉' : '一般' }}</td>
                <td class="fw-bold">{{ s.zone_count }}</td>
                <td>{{ s.total_today }}</td>
                <td>
                  <span v-if="s.feasible" class="text-success">✓</span>
                  <span v-else class="text-danger small">✗ {{ s.reason }}</span>
                </td>
                <td>
                  <button class="btn btn-sm btn-primary" :disabled="!s.feasible"
                          @click="adoptVehicle(zoneSuggest.order.id, s.vehicle_id)">採用</button>
                </td>
              </tr>
            </tbody>
          </table>
          <small class="text-muted">採用＝手動指派此車(狀態轉已排班);時間窗精確可行性以實際排班為準。</small>
        </template>
      </div>
    </div>
  </div>

  <!-- 列表 -->
  <div class="table-responsive">
    <table class="table table-striped table-hover align-middle small">
      <thead>
        <tr>
          <th>日期 / 時間</th>
          <th>乘客</th>
          <th>上車地址</th>
          <th>下車地址</th>
          <th>車種</th>
          <th>指派車輛</th>
          <th>狀態</th>
          <th class="text-end">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="o in pagedOrders" :key="o.id">
          <!-- 日期 / 時間 -->
          <td class="text-nowrap">
            <div>{{ o.service_date }}</div>
            <div class="text-muted">{{ (o.pickup_time || '').slice(11, 16) }}</div>
          </td>
          <!-- 乘客 + 標記 -->
          <td>
            <div>
              <span v-if="o.booking_source && o.booking_source.includes('候補')"
                    class="badge bg-secondary me-1" style="font-size:.62rem">候補</span>
              <span class="fw-semibold">{{ o.passenger_name || '—' }}</span>
            </div>
            <div class="text-muted" style="font-size:.75rem">
              <span v-if="o.payment_type === 'subsidy'" class="badge bg-primary me-1" style="font-size:.6rem">補助</span>
              <span v-else-if="o.payment_type === 'self'" class="badge bg-secondary me-1" style="font-size:.6rem">自費</span>
              <span v-if="o.customer_region">{{ o.customer_region }}</span>
              <span v-if="o.eligibility" class="ms-1 text-muted">{{ o.eligibility }}</span>
            </div>
          </td>
          <!-- 上車地址 -->
          <td style="max-width:200px">
            <div class="text-truncate" :title="o.pickup_address">{{ o.pickup_address }}</div>
            <span v-if="!hasCoords(o)" class="text-warning" style="font-size:.7rem">⚠ 未編碼</span>
          </td>
          <!-- 下車地址 -->
          <td style="max-width:200px">
            <div class="text-truncate" :title="o.dropoff_address">{{ o.dropoff_address }}</div>
          </td>
          <!-- 車種 -->
          <td class="text-nowrap">
            <span class="badge" :class="o.vehicle_type === 'welfare' ? 'bg-warning text-dark' : 'bg-light text-dark border'">
              {{ o.vehicle_type === 'welfare' ? '♿ 福祉' : '一般' }}
            </span>
          </td>
          <!-- 指派車輛 -->
          <td class="text-nowrap">
            <span v-if="o.assigned_vehicle_id" class="badge bg-dark">{{ vehicleLabel(o.assigned_vehicle_id) }}</span>
            <span v-else class="text-muted">—</span>
          </td>
          <!-- 狀態 -->
          <td>
            <span class="badge"
              :class="{
                'bg-success': o.status==='scheduled',
                'bg-primary': o.status==='ongoing',
                'bg-dark':    o.status==='done',
                'bg-secondary': o.status==='canceled',
                'bg-warning text-dark': o.status==='imported',
              }">
              {{ STATUS[o.status] || o.status }}
            </span>
          </td>
          <!-- 操作 -->
          <td class="text-nowrap text-end">
            <button class="btn btn-sm btn-outline-primary me-1" @click="openEdit(o)">編輯</button>
            <button v-if="hasCoords(o) && !['canceled','done'].includes(o.status)"
                    class="btn btn-sm btn-outline-primary me-1" title="最佳車輛建議"
                    @click="openSuggestVeh(o)">💡</button>
            <button v-if="o.status==='scheduled'"
                    class="btn btn-sm btn-outline-success me-1" @click="setStatus(o,'ongoing')">開始</button>
            <button v-if="o.status==='ongoing'"
                    class="btn btn-sm btn-outline-dark me-1" @click="setStatus(o,'done')">完成</button>
            <button v-if="!['canceled','done'].includes(o.status)"
                    class="btn btn-sm btn-outline-warning me-1" @click="cancelOrder(o)">取消</button>
            <button class="btn btn-sm btn-outline-danger" @click="remove(o)">刪除</button>
          </td>
        </tr>
        <tr v-if="!store.items.length">
          <td colspan="8" class="text-center text-muted py-4">尚無訂單，點右上角新增。</td>
        </tr>
      </tbody>
    </table>
    <Pagination :total="store.items.length" v-model:page="currentPage" :page-size="PAGE_SIZE" />
  </div>

  <SuggestVehicle :order="suggestVehOrder"
                  @close="suggestVehOrder = null" @assigned="onVehAssigned" />
</template>

<style scoped>
.zone-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1080;
  padding: 1rem;
}
.zone-card {
  width: 560px;
  max-width: 95vw;
  max-height: 85vh;
  overflow: auto;
}
</style>
