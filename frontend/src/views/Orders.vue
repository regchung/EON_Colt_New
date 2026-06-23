<script setup>
import { onMounted, ref, reactive, computed } from 'vue'
import { useOrdersStore } from '../stores/orders'
import { useVehiclesStore } from '../stores/vehicles'
import client from '../api/client'

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

// --- 批次匯入 ---
const fileInput = ref(null)
const importing = ref(false)
const importReport = ref(null)
const importProgress = ref(null) // { phase, current, total, created, geo_done, geo_failed }

function pickFile() {
  importReport.value = null
  importProgress.value = null
  fileInput.value?.click()
}

async function downloadTemplate() {
  const { data } = await client.get('/orders/import/template', { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = 'smartcar_import_template.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function onFileChosen(e) {
  const file = e.target.files?.[0]
  if (!file) return
  importing.value = true
  importReport.value = null
  importProgress.value = { phase: 'import', current: 0, total: 0, created: 0, geo_done: 0, geo_failed: 0 }

  try {
    const fd = new FormData()
    fd.append('file', file)
    const token = localStorage.getItem('token')
    const resp = await fetch('/api/orders/import', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      importReport.value = { error: err.detail || `HTTP ${resp.status}` }
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() // 保留未完整的行
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const ev = JSON.parse(line.slice(6))
          if (ev.type === 'start') {
            importProgress.value = { phase: 'import', current: 0, total: ev.total, created: 0, geo_done: 0, geo_failed: 0 }
          } else if (ev.type === 'progress' && ev.phase === 'import') {
            importProgress.value = { ...importProgress.value, phase: 'import', current: ev.current, total: ev.total, created: ev.created }
          } else if (ev.type === 'geocode_start') {
            importProgress.value = { ...importProgress.value, phase: 'geocode', current: 0, total: ev.total }
          } else if (ev.type === 'progress' && ev.phase === 'geocode') {
            importProgress.value = { ...importProgress.value, phase: 'geocode', current: ev.current, total: ev.total, geo_done: ev.done, geo_failed: ev.failed }
          } else if (ev.type === 'done') {
            importReport.value = ev
            importProgress.value = null
            await store.fetchAll()
          } else if (ev.type === 'error') {
            importReport.value = { error: ev.message }
            importProgress.value = null
          }
        } catch { /* 忽略解析錯誤 */ }
      }
    }
  } catch (err) {
    importReport.value = { error: err.message || '匯入失敗' }
    importProgress.value = null
  } finally {
    importing.value = false
    e.target.value = ''
  }
}

// --- AI 文件智慧匯入 ---
const docFileInput = ref(null)
const docImporting = ref(false)
const docReport = ref(null)

function pickDocFile() {
  docReport.value = null
  docFileInput.value?.click()
}

async function onDocFileChosen(e) {
  const file = e.target.files?.[0]
  if (!file) return
  docImporting.value = true
  docReport.value = null
  try {
    const fd = new FormData()
    fd.append('file', file)
    // 文件未標日期時,預設用篩選列的服務日期(若有)
    const params = filters.service_date ? { service_date: filters.service_date } : {}
    const { data } = await client.post('/orders/import-doc', fd, { params, timeout: 120000 })
    docReport.value = data
    await store.fetchAll()
  } catch (err) {
    docReport.value = { error: err?.response?.data?.detail || err.message || '匯入失敗' }
  } finally {
    docImporting.value = false
    e.target.value = ''
  }
}

// --- 班表(人工派遣結果)匯入 ---
const schedFileInput = ref(null)
const schedImporting = ref(false)
const schedReport = ref(null)

function pickSchedFile() {
  schedReport.value = null
  schedFileInput.value?.click()
}

async function onSchedFileChosen(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!confirm(`匯入班表「${file.name}」?\n\n這會以班表為人工派遣結果,並「取代」班表內各服務日期既有的訂單與派遣紀錄(假單自動略過)。`)) {
    e.target.value = ''
    return
  }
  schedImporting.value = true
  schedReport.value = null
  try {
    const fd = new FormData()
    fd.append('file', file)
    const { data } = await client.post('/history/import-schedule', fd, {
      params: { replace_date: true },
      timeout: 300000,
    })
    schedReport.value = data
    await store.fetchAll()
  } catch (err) {
    schedReport.value = { error: err?.response?.data?.detail || err.message || '匯入失敗' }
  } finally {
    schedImporting.value = false
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
const aiAnalyzing = ref(false)

async function runDispatch() {
  const sd = filters.service_date || new Date().toISOString().slice(0, 10)
  dispatching.value = true
  dispatchReport.value = null
  try {
    const { data } = await client.post('/dispatch/run', null, { params: { service_date: sd } })
    dispatchReport.value = data
    await store.fetchAll(filters.service_date ? { service_date: sd } : {})
  } catch (err) {
    dispatchReport.value = { error: err?.response?.data?.detail || err.message }
  } finally {
    dispatching.value = false
  }
}

async function runAiAnalyze() {
  const sd = filters.service_date || new Date().toISOString().slice(0, 10)
  aiAnalyzing.value = true
  try {
    const { data } = await client.post('/dispatch/ai-analyze', null, { params: { service_date: sd } })
    if (dispatchReport.value) {
      dispatchReport.value.ai_summary = data.ai_summary
    } else {
      dispatchReport.value = { ai_summary: data.ai_summary, _ai_only: true }
    }
  } catch (err) {
    alert(err?.response?.data?.detail || 'AI 分析失敗')
  } finally {
    aiAnalyzing.value = false
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
  allow_pool: true,
  note: '',
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
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <span class="text-muted">共 {{ store.items.length }} 筆</span>
    <div class="btn-group flex-wrap">
      <button class="btn btn-outline-secondary" @click="downloadTemplate">下載範本</button>
      <button class="btn btn-outline-success" :disabled="importing" @click="pickFile">
        {{ importing ? '匯入中…' : '批次匯入' }}
      </button>
      <button class="btn btn-outline-primary" :disabled="docImporting" @click="pickDocFile"
              title="上傳 PDF/Word/Excel/CSV,由 AI 抽取訂單(內容會送往 Claude)">
        {{ docImporting ? 'AI 解析中…' : '🤖 AI 文件匯入' }}
      </button>
      <button class="btn btn-outline-dark" :disabled="schedImporting" @click="pickSchedFile"
              title="上傳車隊『班表』(人工派遣結果),建訂單+人工派遣歷史供逐車對比;取代當日既有資料">
        {{ schedImporting ? '班表匯入中…' : '📋 班表匯入' }}
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
      ref="fileInput"
      type="file"
      accept=".xlsx,.csv"
      class="d-none"
      @change="onFileChosen"
    />
    <input
      ref="docFileInput"
      type="file"
      accept=".pdf,.docx,.xlsx,.xlsm,.xls,.csv,.txt,.md"
      class="d-none"
      @change="onDocFileChosen"
    />
    <input
      ref="schedFileInput"
      type="file"
      accept=".xlsx,.xls"
      class="d-none"
      @change="onSchedFileChosen"
    />
  </div>

  <!-- 班表(人工派遣結果)匯入報告 -->
  <div v-if="schedImporting" class="alert alert-dark py-2">
    📋 班表匯入中…(逐列地理編碼,未命中地址簿者會打 Map8,請稍候)
  </div>
  <div v-if="schedReport" class="alert" :class="schedReport.error ? 'alert-danger' : 'alert-dark'">
    <template v-if="schedReport.error">班表匯入失敗:{{ schedReport.error }}</template>
    <template v-else>
      <strong>班表匯入完成</strong>(服務日期 {{ (schedReport.dates || []).join('、') }}):
      建立人工派遣 <span class="text-success fw-bold">{{ schedReport.imported }}</span> 筆,
      略過假單 {{ schedReport.skipped_fake }} 筆;
      取代既有訂單 {{ schedReport.deleted_orders }} / 派遣紀錄 {{ schedReport.deleted_history }} 筆。
      地理編碼:命中 {{ schedReport.geocoded }}、未命中 <span :class="schedReport.geocode_miss ? 'text-danger' : ''">{{ schedReport.geocode_miss }}</span>;
      新建車 {{ schedReport.vehicles_created }}、司機 {{ schedReport.drivers_created }}。
      <span class="text-muted">→ 可至「🚐 逐車對比」檢視當日人工 vs 自動。</span>
      <details v-if="schedReport.errors?.length" class="small mt-1">
        <summary class="text-danger">略過/失敗 {{ schedReport.errors.length }} 筆(展開)</summary>
        <ul class="mb-0">
          <li v-for="(er, i) in schedReport.errors" :key="i">{{ er.row }}:{{ er.error }}</li>
        </ul>
      </details>
    </template>
  </div>

  <!-- AI 文件匯入報告 -->
  <div v-if="docImporting" class="alert alert-primary py-2">
    🤖 AI 解析文件中…(抽取訂單需數秒~數十秒,請稍候)
  </div>
  <div v-if="docReport" class="alert" :class="docReport.error ? 'alert-danger' : 'alert-primary'">
    <template v-if="docReport.error">AI 文件匯入失敗:{{ docReport.error }}</template>
    <template v-else>
      <strong>AI 文件匯入完成</strong>(檔案 {{ docReport.filename }}):
      抽取 {{ docReport.extracted }} 筆,建立 <span class="text-success fw-bold">{{ docReport.created }}</span> 筆,
      失敗 <span class="text-danger fw-bold">{{ docReport.failed }}</span> 筆;
      自動編碼成功 {{ docReport.geocoded?.done }} 筆<span v-if="docReport.geocoded?.failed">、失敗 {{ docReport.geocoded.failed }} 筆</span>。
      <div v-if="docReport.preview?.length" class="table-responsive mt-2">
        <table class="table table-sm table-bordered bg-white mb-1">
          <thead><tr><th>日期</th><th>時間</th><th>乘客</th><th>上車</th><th>下車</th><th>車種</th><th>人</th></tr></thead>
          <tbody>
            <tr v-for="(p, i) in docReport.preview" :key="i">
              <td>{{ p.service_date }}</td><td>{{ p.pickup_time }}</td><td>{{ p.passenger_name }}</td>
              <td class="small">{{ p.pickup_address }}</td><td class="small">{{ p.dropoff_address }}</td>
              <td>{{ p.vehicle_type === 'welfare' ? '福祉' : '一般' }}</td><td>{{ p.pax }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details v-if="docReport.errors?.length" class="small">
        <summary class="text-danger">未抽取/失敗 {{ docReport.errors.length }} 筆(展開)</summary>
        <ul class="mb-0">
          <li v-for="(er, i) in docReport.errors" :key="i">{{ er.row }}:{{ er.error }}</li>
        </ul>
      </details>
      <div class="small text-muted mt-1">⚠️ 文件內容(可能含個資)已送往 Claude 抽取;正式處理真實個資前請評估地端方案。</div>
    </template>
  </div>

  <!-- 匯入進度條 -->
  <div v-if="importProgress" class="card mb-3 border-primary">
    <div class="card-body py-2">
      <div class="d-flex justify-content-between small mb-1">
        <span>
          <span v-if="importProgress.phase === 'import'">
            📥 匯入中… {{ importProgress.current }} / {{ importProgress.total }} 列
            （已建立 {{ importProgress.created }} 筆）
          </span>
          <span v-else>
            📍 地理編碼中… {{ importProgress.current }} / {{ importProgress.total }} 筆
            （成功 {{ importProgress.geo_done }}・失敗 {{ importProgress.geo_failed }}）
          </span>
        </span>
        <span class="text-muted">{{ importProgress.total ? Math.round(importProgress.current / importProgress.total * 100) : 0 }}%</span>
      </div>
      <div class="progress" style="height:8px">
        <div
          class="progress-bar progress-bar-striped progress-bar-animated"
          :class="importProgress.phase === 'geocode' ? 'bg-info' : 'bg-primary'"
          :style="{ width: (importProgress.total ? importProgress.current / importProgress.total * 100 : 0) + '%' }"
        ></div>
      </div>
    </div>
  </div>

  <!-- 匯入報告 -->
  <div v-if="importReport" class="alert" :class="importReport.error ? 'alert-danger' : 'alert-info'">
    <template v-if="importReport.error">匯入失敗:{{ importReport.error }}</template>
    <template v-else>
      <strong>匯入完成</strong>(檔案 {{ importReport.filename }}):
      成功 <span class="text-success fw-bold">{{ importReport.created }}</span> 筆,
      失敗 <span class="text-danger fw-bold">{{ importReport.failed }}</span> 筆。
      <span v-if="importReport.geocoded">
        ・自動編碼 <span class="text-success fw-bold">{{ importReport.geocoded.done }}</span> 筆<span
          v-if="importReport.geocoded.failed">,編碼失敗 {{ importReport.geocoded.failed }} 筆</span>。
      </span>
      <ul v-if="importReport.errors?.length" class="mb-0 mt-2 small">
        <li v-for="(er, i) in importReport.errors" :key="i">第 {{ er.row }} 列:{{ er.error }}</li>
      </ul>
    </template>
    <button type="button" class="btn-close float-end" @click="importReport = null"></button>
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
      <div class="d-flex gap-2 align-items-center">
        <button
          class="btn btn-sm btn-outline-primary"
          :disabled="aiAnalyzing"
          @click="runAiAnalyze"
        >{{ aiAnalyzing ? '🤖 分析中…' : '🤖 AI 分析' }}</button>
        <button type="button" class="btn-close" @click="dispatchReport = null"></button>
      </div>
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
    <table class="table table-striped table-hover align-middle">
      <thead>
        <tr>
          <th>#</th><th>日期</th><th>上車時間</th><th>乘客</th>
          <th>上車 → 下車</th><th>📍</th><th>人</th><th>車種</th><th>派遣</th><th>狀態</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="o in store.items" :key="o.id">
          <td>{{ o.id }}</td>
          <td>{{ o.service_date }}</td>
          <td>{{ (o.pickup_time || '').slice(11, 16) }}</td>
          <td>{{ o.passenger_name || '-' }}</td>
          <td class="small">{{ o.pickup_address }} → {{ o.dropoff_address }}</td>
          <td>
            <span v-if="hasCoords(o)" title="已有座標">✅</span>
            <span v-else title="尚未地理編碼" class="text-warning">⚠️</span>
          </td>
          <td>{{ o.pax }}</td>
          <td>
            <span class="badge" :class="o.vehicle_type === 'welfare' ? 'bg-warning text-dark' : 'bg-secondary'">
              {{ o.vehicle_type === 'welfare' ? '福祉' : '一般' }}
            </span>
          </td>
          <td class="small text-nowrap">
            <template v-if="o.assigned_vehicle_id">
              <span class="badge bg-dark">{{ vehicleLabel(o.assigned_vehicle_id) }}</span>
              <span class="text-muted"> #{{ o.dispatch_seq }} · {{ fmtEta(o.eta) }}</span>
            </template>
            <span v-else class="text-muted">—</span>
          </td>
          <td><span class="badge bg-info text-dark">{{ STATUS[o.status] || o.status }}</span></td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-outline-primary me-1" @click="openEdit(o)">編輯</button>
            <button
              v-if="hasCoords(o) && !['canceled','done'].includes(o.status)"
              class="btn btn-sm btn-outline-info me-1"
              title="區域親和建議司機"
              @click="suggestZone(o)"
            >建議</button>
            <button
              v-if="o.status === 'scheduled'"
              class="btn btn-sm btn-outline-success me-1"
              title="標記為進行中(重排時鎖定)"
              @click="setStatus(o, 'ongoing')"
            >開始</button>
            <button
              v-if="o.status === 'ongoing'"
              class="btn btn-sm btn-outline-dark me-1"
              @click="setStatus(o, 'done')"
            >完成</button>
            <button
              v-if="!['canceled','done'].includes(o.status)"
              class="btn btn-sm btn-outline-warning me-1"
              @click="cancelOrder(o)"
            >取消</button>
            <button class="btn btn-sm btn-outline-danger" @click="remove(o)">刪除</button>
          </td>
        </tr>
        <tr v-if="!store.items.length">
          <td colspan="11" class="text-center text-muted py-4">尚無訂單,點右上角新增。</td>
        </tr>
      </tbody>
    </table>
  </div>
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
