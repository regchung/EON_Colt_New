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

function pickFile() {
  importReport.value = null
  fileInput.value?.click()
}

async function downloadTemplate() {
  // 需帶 JWT,故用 axios 取 blob 再觸發下載(不能用純 <a href>)
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
  try {
    const fd = new FormData()
    fd.append('file', file)
    const { data } = await client.post('/orders/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    importReport.value = data
    await store.fetchAll()
  } catch (err) {
    importReport.value = { error: err?.response?.data?.detail || err.message }
  } finally {
    importing.value = false
    e.target.value = '' // 允許重複選同一檔
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
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <span class="text-muted">共 {{ store.items.length }} 筆</span>
    <div class="btn-group flex-wrap">
      <button class="btn btn-outline-secondary" @click="downloadTemplate">下載範本</button>
      <button class="btn btn-outline-success" :disabled="importing" @click="pickFile">
        {{ importing ? '匯入中…' : '批次匯入' }}
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
