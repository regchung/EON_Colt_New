<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

const summary = ref(null)
const rows = ref([])
const fleet = ref('')
const loading = ref(false)
const poolGain = ref(null)
const savings = ref(null)

// 時間窗敏感度(按需執行,VROOM 多跑需數十秒)
const sens = ref(null)
const sensLoading = ref(false)
const sensSampleDays = ref(12)

async function loadSummary() {
  const { data } = await client.get('/dispatch/comparison/summary')
  summary.value = data
}
async function loadSavings() {
  try {
    const { data } = await client.get('/dispatch/comparison/savings')
    savings.value = data
  } catch { /* 無對比資料時略過 */ }
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
function ntd(n) { return 'NT$ ' + (n || 0).toLocaleString('en-US') }
async function loadPoolGain() {
  try {
    const { data } = await client.get('/dispatch/pool-gain')
    if (data.available) poolGain.value = data
  } catch { /* 投影未跑時略過 */ }
}
async function loadRows() {
  loading.value = true
  try {
    const { data } = await client.get('/dispatch/comparison', {
      params: fleet.value ? { fleet: fleet.value, limit: 500 } : { limit: 500 },
    })
    rows.value = data
  } finally {
    loading.value = false
  }
}
onMounted(async () => { await loadSummary(); await loadSavings(); await loadPoolGain(); await loadRows() })

function pct(n) { return (n || 0).toFixed(1) }
// 共乘後相對人工的總節省率
function poolTotalPct() {
  if (!poolGain.value || !summary.value) return 0
  const h = summary.value.group.human_vehicle_days
  return h ? (100 * (h - poolGain.value.group.v_pool) / h).toFixed(1) : 0
}
</script>

<template>
  <template v-if="summary">
    <!-- 集團總覽卡 -->
    <h6 class="text-muted mb-2">集團整體(人工 vs 自動)</h6>
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm border-success"><div class="card-body py-3">
        <div class="display-6 fw-bold text-success">↓{{ pct(summary.group.saved_pct) }}%</div>
        <small class="text-muted">用車節省率</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="h3 fw-bold mb-0">{{ summary.group.human_vehicle_days }} → <span class="text-success">{{ summary.group.vroom_vehicle_days }}</span></div>
        <small class="text-muted">車日:人工 → 自動</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-primary">{{ summary.group.saved_vehicle_days }}</div>
        <small class="text-muted">省下車日合計</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-info">{{ summary.group.days_vroom_better }}/{{ summary.group.days }}</div>
        <small class="text-muted">自動更省的天數</small></div></div></div>
    </div>
    <p class="small text-muted">
      共 {{ summary.group.orders }} 趟成行單;自動排班未排入 {{ summary.group.vroom_unassigned }} 趟(±30 分時間窗)。
      已納入司機實務約束(前後40分/趟、8h工時、06-18時段、共乘需同意),為保守且貼近實務之估計。
    </p>

    <!-- NT$ 換算(車隊報價/ROI) -->
    <div v-if="savings" class="card shadow-sm mb-3 border-success">
      <div class="card-header bg-success-subtle d-flex justify-content-between align-items-center py-2">
        <span>💰 成本效益(省下車日 → NT$)</span>
        <RouterLink to="/settings" class="btn btn-sm btn-outline-secondary">調整成本參數</RouterLink>
      </div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 fw-bold text-success mb-0">{{ ntd(savings.group.annual_saving_ntd) }}</div>
            <small class="text-muted">年化省下成本</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 fw-bold text-primary mb-0">{{ ntd(savings.group.observed_saving_ntd) }}</div>
            <small class="text-muted">實測期間省下({{ savings.group.observed_days }} 日)</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 fw-bold mb-0">{{ ntd(savings.group.per_day_saving_ntd) }}</div>
            <small class="text-muted">平均每營運日省下</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 fw-bold mb-0">{{ savings.group.saved_vehicle_days }} 車日</div>
            <small class="text-muted">@ {{ ntd(savings.cost_per_vehicle_day) }}/車日</small></div></div>
        </div>
        <p class="small text-muted mb-0 mt-2">
          年化 = 平均每營運日省下 × 年營運天數({{ savings.annual_service_days }} 日);
          每車日成本與年營運天數可於「參數設定」調整,以貼近實際報價。
        </p>
      </div>
    </div>

    <!-- 共乘增益 -->
    <div v-if="poolGain" class="card shadow-sm mb-3 border-info">
      <div class="card-header bg-info-subtle d-flex justify-content-between align-items-center py-2">
        <span>🤝 共乘增益(若推薦組取得同意)</span>
        <RouterLink to="/pool-suggest" class="btn btn-sm btn-outline-primary">前往共乘建議</RouterLink>
      </div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 mb-0">{{ summary.group.human_vehicle_days }}
              → {{ summary.group.vroom_vehicle_days }}
              → <span class="text-info fw-bold">{{ poolGain.group.v_pool }}</span></div>
            <small class="text-muted">車日:人工 → 自動 → +共乘</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="display-6 fw-bold text-success">↓{{ poolTotalPct() }}%</div>
            <small class="text-muted">共乘後 vs 人工(總節省)</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="display-6 fw-bold text-primary">+{{ poolGain.group.extra_saved_pct_vs_now }}%</div>
            <small class="text-muted">較現況再省({{ poolGain.group.saved_vehicles }} 車日)</small></div></div>
          <div class="col-6 col-md-3"><div class="text-center">
            <div class="h4 mb-0">{{ poolGain.group.ask_groups }} 組 / {{ poolGain.group.recurring_pairs }} 對</div>
            <small class="text-muted">待徵詢組數 / 常態共乘對</small></div></div>
        </div>
        <p class="small text-muted mb-0 mt-2">
          僅需對 {{ poolGain.group.ask_groups }} 組(約占 2% 趟次)徵得共乘同意,即可把節省由
          ↓{{ pct(summary.group.saved_pct) }}% 推進到 ↓{{ poolTotalPct() }}%;其中 {{ poolGain.group.recurring_pairs }}
          對為反覆同行,適合一次徵長期同意。
        </p>
      </div>
    </div>

    <!-- 時間窗敏感度 -->
    <div class="card shadow-sm mb-3 border-primary">
      <div class="card-header bg-primary-subtle d-flex flex-wrap justify-content-between align-items-center gap-2 py-2">
        <span>⏱️ 時間窗敏感度(放寬上車彈性 → 省更多車 vs 未派)</span>
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
          觀察「放寬上車彈性對省車數與未派趟次的影響」。每窗一輪,約需數十秒。
        </p>
        <div v-if="sens" class="table-responsive">
          <table class="table table-sm text-center align-middle mb-2">
            <thead class="table-light"><tr>
              <th>上車時間窗</th><th>省車率</th><th>人工→自動車日</th><th>省下車日</th><th>未派趟次</th><th>未派率</th>
            </tr></thead>
            <tbody>
              <tr v-for="w in sens.windows" :key="w.window_min">
                <td class="fw-semibold">±{{ w.window_min }} 分</td>
                <td><span class="badge bg-success">↓{{ pct(w.saved_pct) }}%</span></td>
                <td>{{ w.human_vehicle_days }} → <span class="text-success fw-bold">{{ w.vroom_vehicle_days }}</span></td>
                <td>{{ w.saved_vehicle_days }}</td>
                <td :class="{ 'text-danger': w.vroom_unassigned }">{{ w.vroom_unassigned }}</td>
                <td>{{ pct(w.unassigned_pct) }}%</td>
              </tr>
            </tbody>
          </table>
          <p class="small text-muted mb-0">
            取樣 {{ sens.sample_days }} 天、共 {{ sens.windows[0]?.orders }} 趟。時間窗越寬、彈性越大 → 通常用車越省;
            未派趟次多為 06–18 服務時段外者(放寬上車窗救不回)。供報價與 SLA(承諾準時彈性)權衡參考。
          </p>
        </div>
      </div>
    </div>

    <!-- 各車行 -->
    <h6 class="text-muted mb-2 mt-3">各車行</h6>
    <div class="table-responsive mb-4">
      <table class="table table-sm table-striped align-middle">
        <thead><tr><th>車行</th><th>天數</th><th>成行單</th><th>人工車日</th><th>自動車日</th><th>節省率</th><th>更省天數</th><th>未派</th></tr></thead>
        <tbody>
          <tr v-for="(s, f) in summary.by_fleet" :key="f">
            <td class="fw-semibold">{{ f }}</td>
            <td>{{ s.days }}</td><td>{{ s.orders }}</td>
            <td>{{ s.human_vehicle_days }}</td>
            <td class="text-success fw-bold">{{ s.vroom_vehicle_days }}</td>
            <td><span class="badge" :class="s.saved_pct > 0 ? 'bg-success' : 'bg-secondary'">↓{{ pct(s.saved_pct) }}%</span></td>
            <td>{{ s.days_vroom_better }}/{{ s.days }}</td>
            <td :class="{ 'text-danger': s.vroom_unassigned }">{{ s.vroom_unassigned }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>

  <!-- 逐日明細 -->
  <div class="d-flex align-items-center gap-2 mb-2">
    <h6 class="text-muted mb-0 me-auto">逐日明細(依省車數排序)</h6>
    <select v-model="fleet" class="form-select form-select-sm" style="width:auto" @change="loadRows">
      <option value="">全部車行</option>
      <option v-for="(s, f) in (summary?.by_fleet || {})" :key="f" :value="f">{{ f }}</option>
    </select>
  </div>
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead><tr>
        <th>日期</th><th>車行</th><th>成行單</th><th>人工車</th><th>自動車</th><th>省車</th><th>未派</th><th>人工里程</th><th>自動行駛</th>
      </tr></thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="i">
          <td>{{ r.service_date }}</td><td>{{ r.fleet }}</td><td>{{ r.n_orders }}</td>
          <td>{{ r.human_vehicles }}</td>
          <td class="text-success fw-bold">{{ r.vroom_vehicles }}</td>
          <td><span v-if="r.saved_vehicles > 0" class="badge bg-success">-{{ r.saved_vehicles }}</span><span v-else>0</span></td>
          <td :class="{ 'text-danger': r.vroom_unassigned }">{{ r.vroom_unassigned }}</td>
          <td class="small text-muted">{{ r.human_distance_km }} km</td>
          <td class="small text-muted">{{ r.vroom_drive_min }} 分</td>
        </tr>
        <tr v-if="!rows.length"><td colspan="9" class="text-center text-muted py-4">尚無對比資料</td></tr>
      </tbody>
    </table>
  </div>
</template>
