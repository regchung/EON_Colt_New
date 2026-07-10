<script setup>
import { onMounted, ref, computed } from 'vue'
import client from '../api/client'
import TrendChart from '../components/TrendChart.vue'

const today = new Date().toISOString().slice(0, 10)
const ago13 = new Date(Date.now() - 13 * 86400000).toISOString().slice(0, 10)
const dateFrom = ref(ago13)
const dateTo = ref(today)
const data = ref(null)
const loading = ref(false)

const STATUS_LABEL = { imported: '待排', scheduled: '已排', ongoing: '進行中', done: '完成', canceled: '取消' }

async function load() {
  loading.value = true
  try {
    const res = await client.get('/reports/overview', {
      params: { date_from: dateFrom.value, date_to: dateTo.value },
    })
    data.value = res.data
  } finally {
    loading.value = false
  }
}
onMounted(load)

// --- 派遣表匯出(挑日期 + 車行 + 版型)---
const fleets = ref([])
const expDate = ref(today)
const expFleet = ref('')          // '' = 全車行
const expLayout = ref('single')   // single | per_vehicle
const expLoading = ref(false)
async function loadFleets() {
  try {
    const { data: m } = await client.get('/dispatch/daily-tasks/meta')
    fleets.value = m.fleets || []
    if (m.max_date) expDate.value = m.max_date
  } catch { /* 略過 */ }
}
onMounted(loadFleets)
async function exportDispatch() {
  expLoading.value = true
  try {
    const res = await client.get('/dispatch/export', {
      params: { service_date: expDate.value, fleet: expFleet.value || undefined,
                layout: expLayout.value },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    const tag = expLayout.value === 'per_vehicle' ? '每車表' : '總表'
    a.download = `EON_COLT_派遣_${expDate.value}_${expFleet.value || '全車行'}_${tag}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(e.response?.data?.detail || '匯出失敗')
  } finally {
    expLoading.value = false
  }
}

async function exportCsv() {
  const res = await client.get('/reports/export-csv', {
    params: { date_from: dateFrom.value, date_to: dateTo.value, source: source.value },
    responseType: 'blob',
  })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  const tag = '派遣'
  a.download = `eon_colt_${tag}_${dateFrom.value}_${dateTo.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function pct(n, total) {
  return total ? Math.round((n / total) * 100) : 0
}

// 趨勢圖資料(由 by_day 推導)
const trendLabels = computed(() => (data.value?.by_day || []).map((d) => d.date.slice(5)))
const volumeSeries = computed(() => [
  { name: '總數', color: '#4363d8', values: (data.value?.by_day || []).map((d) => d.total) },
  { name: '已派', color: '#3cb44b', values: (data.value?.by_day || []).map((d) => d.assigned) },
  { name: '未派', color: '#e6194B', values: (data.value?.by_day || []).map((d) => d.unassigned), dashed: true },
])
const rateSeries = computed(() => [
  { name: '派遣率%', color: '#f58231',
    values: (data.value?.by_day || []).map((d) => pct(d.assigned, d.total)) },
])
</script>

<template>
  <!-- 派遣表匯出 -->
  <div class="card shadow-sm mb-3 border-primary">
    <div class="card-header py-2 fw-semibold">📊 派遣表匯出（Excel）</div>
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div class="col-6 col-md-3">
          <label class="form-label mb-1 small">日期</label>
          <input v-model="expDate" type="date" class="form-control form-control-sm" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label mb-1 small">車行</label>
          <select v-model="expFleet" class="form-select form-select-sm">
            <option value="">全車行</option>
            <option v-for="f in fleets" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>
        <div class="col-12 col-md-4">
          <label class="form-label mb-1 small d-block">版型</label>
          <div class="btn-group btn-group-sm" role="group">
            <input v-model="expLayout" type="radio" class="btn-check" id="lay1" value="single" />
            <label class="btn btn-outline-primary" for="lay1">所有資料一個檔(多分頁)</label>
            <input v-model="expLayout" type="radio" class="btn-check" id="lay2" value="per_vehicle" />
            <label class="btn btn-outline-primary" for="lay2">每車一張工作表</label>
          </div>
        </div>
        <div class="col-12 col-md-2">
          <button class="btn btn-sm btn-primary w-100" :disabled="expLoading" @click="exportDispatch">
            <span v-if="expLoading" class="spinner-border spinner-border-sm me-1"></span>⬇ 產生 Excel
          </button>
        </div>
      </div>
      <div class="small text-muted mt-2">
        「所有資料一個檔」= 總覽/各子車隊/每車排班/派車明細/未派 五分頁;「每車一張工作表」= 每台車獨立派車單 + 總覽。
      </div>
    </div>
  </div>

  <div v-if="data && data.note" class="alert alert-warning py-1 px-2 small mb-2">{{ data.note }}</div>

  <div class="d-flex flex-wrap gap-2 align-items-end mb-3">
    <div><label class="form-label mb-1 small">起</label>
      <input v-model="dateFrom" type="date" class="form-control form-control-sm" style="width:160px" /></div>
    <div><label class="form-label mb-1 small">迄</label>
      <input v-model="dateTo" type="date" class="form-control form-control-sm" style="width:160px" /></div>
    <button class="btn btn-sm btn-primary" :disabled="loading" @click="load">{{ loading ? '查詢中…' : '查詢' }}</button>
    <button class="btn btn-sm btn-outline-secondary" @click="exportCsv">⬇ 匯出 CSV</button>
  </div>

  <template v-if="data">
    <!-- 統計卡 -->
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-primary">{{ data.totals.orders }}</div><small class="text-muted">訂單總數</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-success">{{ data.totals.assigned }}</div><small class="text-muted">已派遣</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-danger">{{ data.totals.unassigned }}</div><small class="text-muted">未派遣</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-info">{{ data.totals.vehicles_active }}/{{ data.totals.vehicles_total }}</div><small class="text-muted">可用/總車輛</small></div></div></div>
    </div>

    <!-- 區間營運趨勢 -->
    <div class="card shadow-sm mb-3"><div class="card-body">
      <h6 class="mb-2">區間營運趨勢（{{ data.date_from.slice(5) }} ～ {{ data.date_to.slice(5) }}）</h6>
      <TrendChart v-if="data.by_day.length > 1" :labels="trendLabels" :series="volumeSeries" :height="240" unit=" 趟" />
      <p v-else class="text-muted small mb-0">區間需 2 天以上才繪製趨勢線。</p>
    </div></div>

    <div class="row g-3">
      <!-- 狀態分佈 -->
      <div class="col-12 col-lg-6"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>訂單狀態分佈</h6>
        <div v-for="(cnt, st) in data.by_status" :key="st" class="mb-2">
          <div class="d-flex justify-content-between small"><span>{{ STATUS_LABEL[st] || st }}</span><span>{{ cnt }}</span></div>
          <div class="progress" style="height:8px"><div class="progress-bar" :style="{ width: pct(cnt, data.totals.orders) + '%' }"></div></div>
        </div>
      </div></div></div>

      <!-- 車種分佈 -->
      <div class="col-12 col-lg-6"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>車種需求分佈</h6>
        <div v-for="(cnt, vt) in data.by_vehicle_type" :key="vt" class="mb-2">
          <div class="d-flex justify-content-between small"><span>{{ vt === 'welfare' ? '福祉車' : '一般車' }}</span><span>{{ cnt }}</span></div>
          <div class="progress" style="height:8px">
            <div class="progress-bar" :class="vt === 'welfare' ? 'bg-warning' : 'bg-secondary'" :style="{ width: pct(cnt, data.totals.orders) + '%' }"></div>
          </div>
        </div>
      </div></div></div>

      <!-- 派遣率趨勢 -->
      <div class="col-12 col-lg-7"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>每日派遣率趨勢</h6>
        <TrendChart v-if="data.by_day.length > 1" :labels="trendLabels" :series="rateSeries" :height="200" unit="%" />
        <p v-else class="text-muted small mb-0">區間需 2 天以上才繪製趨勢線。</p>
      </div></div></div>

      <!-- 每車派遣量 -->
      <div class="col-12 col-lg-5"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>各車派遣量</h6>
        <table class="table table-sm mb-0">
          <tbody>
            <tr v-for="v in data.per_vehicle" :key="v.vehicle_id">
              <td>{{ v.plate }}</td><td class="text-end fw-bold">{{ v.orders }}</td>
            </tr>
            <tr v-if="!data.per_vehicle.length"><td colspan="2" class="text-muted text-center">區間內無派遣</td></tr>
          </tbody>
        </table>
      </div></div></div>
    </div>
  </template>
</template>
