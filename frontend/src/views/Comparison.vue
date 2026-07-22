<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

const summary = ref(null)
const rows = ref([])
const fleet = ref('')
const loading = ref(false)

// 時間窗敏感度(按需執行,VROOM 多跑需數十秒)
const sens = ref(null)
const sensLoading = ref(false)
const sensSampleDays = ref(12)

async function loadSummary() {
  const { data } = await client.get('/dispatch/comparison/summary')
  summary.value = data
}
async function runSensitivity() {
  sensLoading.value = true
  try {
    const { data } = await client.get('/dispatch/comparison/sensitivity', {
      params: { windows: '15,30,45,60', sample_days: sensSampleDays.value, ...(fleet.value ? { fleet: fleet.value } : {}) },
      timeout: 300000,
    })
    sens.value = data
  } finally {
    sensLoading.value = false
  }
}

// 日期區間 + 匯出
const rangeFrom = ref('')
const rangeTo = ref('')
const exporting = ref(false)

function rangeParams() {
  return {
    ...(fleet.value ? { fleet: fleet.value } : {}),
    ...(rangeFrom.value ? { date_from: rangeFrom.value } : {}),
    ...(rangeTo.value ? { date_to: rangeTo.value } : {}),
  }
}
async function loadRows() {
  loading.value = true
  try {
    const { data } = await client.get('/dispatch/comparison', { params: { limit: 500, ...rangeParams() } })
    rows.value = data
  } finally {
    loading.value = false
  }
}
function dl(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `DR_FISH_${name}`; a.click(); URL.revokeObjectURL(url)
}
async function exportSummary() {
  if (!rangeFrom.value || !rangeTo.value) { alert('請先選日期區間'); return }
  exporting.value = true
  try {
    const res = await client.get('/dispatch/comparison/export', { params: rangeParams(), responseType: 'blob' })
    dl(res.data, `自動派遣_${rangeFrom.value}_${rangeTo.value}_${fleet.value || '全車行'}.xlsx`)
  } catch (e) { alert(e.response?.data?.detail || '匯出失敗') } finally { exporting.value = false }
}

onMounted(async () => { await loadSummary(); await loadRows() })

function pct(n) { return (n || 0).toFixed(1) }
</script>

<template>
  <template v-if="summary">
    <!-- 集團總覽卡 -->
    <h6 class="text-muted mb-2">自動排班整體概況</h6>
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-primary"><div class="card-body py-3">
        <div class="display-6 fw-bold text-primary">{{ summary.group.orders }}</div>
        <small class="text-muted">成行單總數</small></div></div></div>
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-secondary"><div class="card-body py-3">
        <div class="display-6 fw-bold text-secondary">{{ summary.group.human_vehicle_days }}</div>
        <small class="text-muted">人工用車日</small></div></div></div>
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-success"><div class="card-body py-3">
        <div class="display-6 fw-bold text-success">{{ summary.group.vroom_vehicle_days }}</div>
        <small class="text-muted">自動用車日</small></div></div></div>
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-warning"><div class="card-body py-3">
        <div class="display-6 fw-bold text-warning">{{ summary.group.saved_vehicle_days }}</div>
        <small class="text-muted">節省車輛日</small></div></div></div>
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-warning"><div class="card-body py-3">
        <div class="display-6 fw-bold text-warning">{{ pct(summary.group.saved_pct) }}%</div>
        <small class="text-muted">節省比例</small></div></div></div>
      <div class="col-6 col-md-2"><div class="card text-center shadow-sm border-danger"><div class="card-body py-3">
        <div class="display-6 fw-bold text-danger">{{ summary.group.vroom_unassigned }}</div>
        <small class="text-muted">未排入趟次</small></div></div></div>
    </div>
    <p class="small text-muted">
      共 {{ summary.group.orders }} 趟成行單；自動排班 <b class="text-success">節省 {{ summary.group.saved_vehicle_days }} 台車日（{{ pct(summary.group.saved_pct) }}%）</b>，
      未排入 {{ summary.group.vroom_unassigned }} 趟（±{{ summary.group.window_min || 30 }} 分時間窗）。
      已納入司機實務約束（前後40分/趟、8h工時、06-18時段、共乘需同意），為保守且貼近實務之估計。
    </p>

    <!-- 時間窗敏感度 -->
    <div class="card shadow-sm mb-3 border-primary">
      <div class="card-header bg-primary-subtle d-flex flex-wrap justify-content-between align-items-center gap-2 py-2">
        <span>⏱️ 時間窗敏感度(放寬上車彈性 → 用車與未派變化)</span>
        <div class="d-flex align-items-center gap-2">
          <label class="small mb-0">取樣天數</label>
          <input v-model.number="sensSampleDays" type="number" min="3" max="40" class="form-control form-control-sm" style="width:5rem" />
          <button class="btn btn-sm btn-primary" :disabled="sensLoading" @click="runSensitivity">
            <span v-if="sensLoading" class="spinner-border spinner-border-sm me-1"></span>{{ sensLoading ? '計算中…' : '執行分析' }}
          </button>
        </div>
      </div>
      <div class="card-body">
        <p v-if="!sens && !sensLoading" class="text-muted small mb-0">
          取最忙的 N 天{{ fleet ? `(${fleet})` : '(全車行)' }},在 15/30/45/60 分時間窗下各重跑一次自動派遣,
          觀察「放寬上車彈性對用車數與未派趟次的影響」。每窗一輪,約需數十秒。
        </p>
        <div v-if="sens" class="table-responsive">
          <table class="table table-sm text-center align-middle mb-2">
            <thead class="table-light"><tr>
              <th>上車時間窗</th><th>自動用車日</th><th>未派趟次</th><th>未派率</th>
            </tr></thead>
            <tbody>
              <tr v-for="w in sens.windows" :key="w.window_min">
                <td class="fw-semibold">±{{ w.window_min }} 分</td>
                <td class="text-success fw-bold">{{ w.vroom_vehicle_days }}</td>
                <td :class="{ 'text-danger': w.vroom_unassigned }">{{ w.vroom_unassigned }}</td>
                <td>{{ pct(w.unassigned_pct) }}%</td>
              </tr>
            </tbody>
          </table>
          <p class="small text-muted mb-0">
            取樣 {{ sens.sample_days }} 天、共 {{ sens.windows[0]?.orders }} 趟。時間窗越寬、彈性越大 → 通常用車越少;
            未派趟次多為 06–18 服務時段外者(放寬上車窗救不回)。供 SLA(承諾準時彈性)與用車效率權衡參考。
          </p>
        </div>
      </div>
    </div>

    <!-- 各車行（多車行時才顯示） -->
    <template v-if="Object.keys(summary?.by_fleet || {}).length > 1">
    <h6 class="text-muted mb-2 mt-3">各車行效益</h6>
    <div class="table-responsive mb-4">
      <table class="table table-sm table-striped align-middle">
        <thead><tr><th>車行</th><th>天數</th><th>成行單</th><th>人工用車日</th><th>自動用車日</th><th>節省台日</th><th>節省%</th><th>未排入</th></tr></thead>
        <tbody>
          <tr v-for="(s, f) in summary.by_fleet" :key="f">
            <td class="fw-semibold">{{ f }}</td>
            <td>{{ s.days }}</td><td>{{ s.orders }}</td>
            <td class="text-secondary">{{ s.human_vehicle_days }}</td>
            <td class="text-success fw-bold">{{ s.vroom_vehicle_days }}</td>
            <td :class="s.saved_vehicle_days > 0 ? 'text-success fw-bold' : s.saved_vehicle_days < 0 ? 'text-danger' : ''">
              {{ s.saved_vehicle_days > 0 ? '+' : '' }}{{ s.saved_vehicle_days }}</td>
            <td :class="s.saved_pct > 0 ? 'text-success' : s.saved_pct < 0 ? 'text-danger' : ''">
              {{ pct(s.saved_pct) }}%</td>
            <td :class="{ 'text-danger': s.vroom_unassigned }">{{ s.vroom_unassigned }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    </template><!-- /各車行 -->
  </template><!-- /v-if summary -->

  <!-- 逐日明細:區間查詢 + 匯出 -->
  <div class="card shadow-sm mb-2 border-primary"><div class="card-body py-2">
    <div class="row g-2 align-items-end">
      <div class="col-6 col-md-2"><label class="form-label mb-0 small">起日</label>
        <input v-model="rangeFrom" type="date" class="form-control form-control-sm" /></div>
      <div class="col-6 col-md-2"><label class="form-label mb-0 small">迄日</label>
        <input v-model="rangeTo" type="date" class="form-control form-control-sm" /></div>
      <div v-if="Object.keys(summary?.by_fleet || {}).length > 1" class="col-6 col-md-3"><label class="form-label mb-0 small">車行</label>
        <select v-model="fleet" class="form-select form-select-sm">
          <option value="">全部車行</option>
          <option v-for="(s, f) in (summary?.by_fleet || {})" :key="f" :value="f">{{ f }}</option>
        </select></div>
      <div class="col-6 col-md-2">
        <button class="btn btn-sm btn-primary w-100" :disabled="loading" @click="loadRows">查詢</button></div>
      <div class="col-6 col-md-3">
        <button class="btn btn-sm btn-success w-100" :disabled="exporting" @click="exportSummary">
          <span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>⬇ 匯出排班報告</button></div>
    </div>
  </div></div>
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead><tr>
        <th>日期</th><th>車行</th><th>成行單</th><th>人工用車</th><th>自動用車</th><th>節省台</th><th>未排入</th><th>自動行駛時間</th>
      </tr></thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="i">
          <td>{{ r.service_date }}</td><td>{{ r.fleet }}</td><td>{{ r.n_orders }}</td>
          <td class="text-secondary">{{ r.human_vehicles }}</td>
          <td class="text-success fw-bold">{{ r.vroom_vehicles }}</td>
          <td :class="r.saved_vehicles > 0 ? 'text-success fw-bold' : r.saved_vehicles < 0 ? 'text-danger' : ''">
            {{ r.saved_vehicles > 0 ? '+' : '' }}{{ r.saved_vehicles }}</td>
          <td :class="{ 'text-danger': r.vroom_unassigned }">{{ r.vroom_unassigned }}</td>
          <td class="small text-muted">{{ r.vroom_drive_min }} 分</td>
        </tr>
        <tr v-if="!rows.length"><td colspan="6" class="text-center text-muted py-4">尚無排班資料</td></tr>
      </tbody>
    </table>
  </div>
</template>
