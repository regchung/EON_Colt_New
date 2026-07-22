<script setup>
import { computed, onMounted, ref } from 'vue'
import client from '../api/client'

// 可選的(車行,日期):取自已算過的逐日對比明細
const days = ref([])          // [{fleet, service_date, n_orders, saved_vehicles}]
const fleet = ref('')
const serviceDate = ref('')
const windowMin = ref(null)   // 預設用系統上車窗(與看板/落地一致);null → 載入後由設定填入

const data = ref(null)
const loading = ref(false)
const error = ref('')

const fleets = computed(() => [...new Set(days.value.map((d) => d.fleet))].sort())
const datesForFleet = computed(() =>
  days.value.filter((d) => d.fleet === fleet.value).map((d) => d.service_date),
)

async function loadWindow() {
  // 逐車比對預設用「系統上車窗」,與看板/落地報表一致。優先由設定填入顯示值(限管理員);
  // 非管理員讀不到設定 → windowMin 保持 null,load() 不帶參數,後端自動用系統上車窗。
  try {
    const { data } = await client.get('/settings')
    const w = data.find((s) => s.key === 'pickup_window_min')
    if (w && windowMin.value == null) windowMin.value = Number(w.value)
  } catch { /* 無管理員權限:留 null,由後端套系統值 */ }
}

async function loadDays() {
  // 有成行單 + 人工派遣紀錄的(車行,日期);不依賴對比批次,匯入班表後即時可選
  const { data: rows } = await client.get('/dispatch/comparison/available-days')
  days.value = rows.sort(
    (a, b) => b.service_date.localeCompare(a.service_date) || a.fleet.localeCompare(b.fleet),
  )
  if (!fleet.value && fleets.value.length) fleet.value = fleets.value[0]
  if (!serviceDate.value && datesForFleet.value.length) serviceDate.value = datesForFleet.value[0]
}

async function load() {
  if (!fleet.value || !serviceDate.value) return
  loading.value = true
  error.value = ''
  data.value = null
  try {
    const { data: r } = await client.get('/dispatch/comparison/by-vehicle', {
      params: {
        fleet: fleet.value, service_date: serviceDate.value,
        ...(windowMin.value != null ? { window_min: windowMin.value } : {}),   // null → 後端用系統上車窗
      },
      timeout: 120000,
    })
    data.value = r
  } catch (err) {
    error.value = err.response?.data?.detail || '載入失敗(可能當日無人工派遣紀錄)'
  } finally {
    loading.value = false
  }
}

function onFleetChange() {
  serviceDate.value = datesForFleet.value[0] || ''
}

onMounted(async () => {
  await loadWindow()
  await loadDays()
  await load()
})

const REASON_LABEL = {
  out_of_hours: '服務時段外',
  no_welfare: '無福祉車',
  unroutable: '無法路由',
  suspect_geocode: '座標疑誤',
  fleet_saturated: '全車隊滿載',
  solver_margin: '求解邊際',
  infeasible: '排不進',
}
function reasonLabel(c) { return REASON_LABEL[c] || c || '排不進' }
function reasonClass(c) {
  if (c === 'suspect_geocode') return 'bg-warning text-dark'
  if (c === 'fleet_saturated') return 'bg-danger'
  if (c === 'solver_margin') return 'bg-info text-dark'
  return 'bg-secondary'
}

// 顯示用:差異車輛排前面
const sortedVehicles = computed(() => {
  if (!data.value) return []
  return [...data.value.vehicles].sort((a, b) => {
    const ad = a.human.n - a.auto.n
    const bd = b.human.n - b.auto.n
    return Math.abs(bd) - Math.abs(ad) || (a.plate || '').localeCompare(b.plate || '')
  })
})
</script>

<template>
  <!-- 篩選列 -->
  <div class="card shadow-sm mb-3">
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div v-if="fleets.length > 1" class="col-6 col-md-3">
          <label class="form-label small mb-1">車行</label>
          <select v-model="fleet" class="form-select" @change="onFleetChange">
            <option v-for="f in fleets" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label small mb-1">日期</label>
          <select v-model="serviceDate" class="form-select">
            <option v-for="d in datesForFleet" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div class="col-6 col-md-2">
          <label class="form-label small mb-1">上車時間窗(分)</label>
          <input v-model.number="windowMin" type="number" min="5" max="120" class="form-control" />
        </div>
        <div class="col-6 col-md-2">
          <button class="btn btn-primary w-100" :disabled="loading" @click="load">
            <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
            載入對比
          </button>
        </div>
      </div>
      <p class="small text-muted mt-2 mb-0">
        左=人工當天實際派遣;右=系統(VROOM)在<strong>同一組實體車輛</strong>上重排。
        <span class="badge bg-warning text-dark">換車</span> 標示該趟在兩邊被指派到不同車。
      </p>
    </div>
  </div>

  <div v-if="error" class="alert alert-warning">{{ error }}</div>

  <template v-if="data">
    <!-- 總覽 -->
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="h4 mb-0">{{ data.n_orders }}</div><small class="text-muted">成行趟次</small>
      </div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm border-secondary"><div class="card-body py-3">
        <div class="h4 mb-0">{{ data.totals.human.vehicles }} <small class="text-muted">→</small>
          <span class="text-success">{{ data.totals.auto.vehicles }}</span></div>
        <small class="text-muted">用車數(人工→自動)</small>
      </div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="h4 mb-0">
          {{ data.totals.human.distance_km }}
          <small class="text-muted">→ {{ data.totals.auto.distance_km ?? '—' }}</small>
        </div><small class="text-muted">總里程 km(人工→自動)</small>
      </div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="h4 mb-0">{{ data.totals.human.work_min }}
          <small class="text-muted">→ {{ data.totals.auto.work_min }}</small></div>
        <small class="text-muted">總工時 分(人工→自動)</small>
      </div></div></div>
    </div>

    <p class="small text-muted">
      里程與工時皆為「實際路徑(含車輛調度空車段)+ 每趟前後 40 分作業」之同方法學估算,左右可直接比較。
      自動側顯示<strong>真實停靠序</strong>(交錯上/下車 + 到點時刻 + 在車人數),共乘一目了然;
      已加上「最長乘車時間」上限(直達車程 × 1.8 + 30 分),避免把乘客在車上載太久。
      <span v-if="!data.distance_available" class="text-warning">
        ⚠️ 目前矩陣來源未提供距離,里程以「—」顯示(設 MATRIX_PROVIDER=osrm 後重跑)。
      </span>
    </p>

    <!-- 自動未派(附可行動原因)-->
    <div v-if="data.auto_unassigned.length" class="alert alert-danger py-2">
      <strong>自動未派 {{ data.auto_unassigned.length }} 趟</strong>(人工有派,系統排不進):
      <ul class="mb-0 mt-1 ps-3 small">
        <li v-for="u in data.auto_unassigned" :key="u.order_id">
          <span class="badge me-1" :class="reasonClass(u.reason_code)">{{ reasonLabel(u.reason_code) }}</span>
          {{ u.pickup_hm }} <span v-if="u.passenger" class="fw-semibold">{{ u.passenger }}</span>
          <span class="text-muted">{{ u.pickup_addr }} → {{ u.dropoff_addr }}</span>
          <span class="text-muted d-block">{{ u.reason_detail }}</span>
        </li>
      </ul>
    </div>

    <!-- 逐車並排 -->
    <div v-for="v in sortedVehicles" :key="v.plate" class="card shadow-sm mb-3">
      <div class="card-header d-flex flex-wrap justify-content-between align-items-center gap-2">
        <div>
          <strong>{{ v.plate }}</strong>
          <span v-if="v.driver" class="ms-2">🧑‍✈️ {{ v.driver }}</span>
          <span class="badge ms-2" :class="v.type === 'welfare' ? 'bg-warning text-dark' : 'bg-secondary'">
            {{ v.type === 'welfare' ? '福祉車' : '一般車' }}
          </span>
          <span class="text-muted small ms-2">{{ v.seats }} 座</span>
        </div>
        <div class="small">
          <span v-if="v.human_used && !v.auto_used" class="badge bg-success">自動省下此車</span>
          <span v-else-if="v.human.n !== v.auto.n" class="badge bg-info text-dark">
            趟次 {{ v.human.n }} → {{ v.auto.n }}
          </span>
        </div>
      </div>
      <div class="row g-0">
        <!-- 人工 -->
        <div class="col-md-6 border-end">
          <div class="px-3 py-2 bg-light small fw-bold d-flex justify-content-between">
            <span>👤 人工派遣({{ v.human.n }} 趟)</span>
            <span class="text-muted">
              {{ v.human.distance_km ?? '—' }} km · 行駛 {{ v.human.drive_min }} 分 · 工時 {{ v.human.work_min }} 分
            </span>
          </div>
          <ul class="list-group list-group-flush">
            <li v-for="(o, i) in v.human.orders" :key="i"
                class="list-group-item py-2" :class="{ 'bg-warning-subtle': o.moved }">
              <div class="d-flex justify-content-between">
                <span>
                  <span class="badge bg-secondary me-1">{{ o.pickup_hm }}</span>
                  <span v-if="o.passenger" class="fw-semibold me-1">{{ o.passenger }}</span>
                  <span class="text-muted">{{ o.pickup_addr }}</span>
                </span>
                <small class="text-muted text-nowrap ms-2">{{ o.distance_km }}km</small>
              </div>
              <div class="small text-muted">→ {{ o.dropoff_addr }}
                <span v-if="o.moved" class="badge bg-warning text-dark ms-1">換車</span>
              </div>
            </li>
            <li v-if="!v.human.orders.length" class="list-group-item text-muted small py-2">人工當日未用此車</li>
          </ul>
        </div>
        <!-- 自動:真實停靠序(交錯上/下車,顯示到點時刻與在車人數)-->
        <div class="col-md-6">
          <div class="px-3 py-2 bg-light small fw-bold d-flex justify-content-between">
            <span>🤖 自動派遣({{ v.auto.n }} 趟 · {{ (v.auto.stops || []).length }} 停)</span>
            <span class="text-muted">
              {{ v.auto.distance_km ?? '—' }} km · 行駛 {{ v.auto.drive_min }} 分 · 工時 {{ v.auto.work_min }} 分
            </span>
          </div>
          <ul class="list-group list-group-flush">
            <li v-for="(s, i) in v.auto.stops" :key="i"
                class="list-group-item py-1 d-flex align-items-center"
                :class="{ 'bg-success-subtle': s.moved && s.kind === '上車' }">
              <span class="badge me-2" :class="s.kind === '上車' ? 'bg-primary' : 'bg-secondary'">{{ s.eta }}</span>
              <span class="me-1" :class="s.kind === '上車' ? 'text-primary' : 'text-secondary'">
                {{ s.kind === '上車' ? '▲上車' : '▼下車' }}
              </span>
              <span v-if="s.passenger" class="fw-semibold me-1">{{ s.passenger }}</span>
              <span class="text-muted small text-truncate">{{ s.addr }}</span>
              <span class="badge bg-light text-dark border ms-auto" title="此刻車上人數">在車 {{ s.onboard }}</span>
              <span v-if="s.moved && s.kind === '上車'" class="badge bg-success ms-1">換入</span>
            </li>
            <li v-if="!(v.auto.stops || []).length" class="list-group-item text-success small py-2">系統未使用此車(省下)</li>
          </ul>
        </div>
      </div>
    </div>
  </template>

  <p v-else-if="!loading && !error" class="text-muted">請選擇車行與日期後點「載入對比」。</p>
</template>
