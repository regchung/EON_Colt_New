<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

const summary = ref(null)
const rows = ref([])
const fleet = ref('')
const loading = ref(false)
const poolGain = ref(null)

async function loadSummary() {
  const { data } = await client.get('/dispatch/comparison/summary')
  summary.value = data
}
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
onMounted(async () => { await loadSummary(); await loadPoolGain(); await loadRows() })

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
