<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

// --- 常態共乘對(P3)---
const recurring = ref([])
const recurringLoading = ref(false)
async function loadRecurring() {
  recurringLoading.value = true
  try {
    const { data } = await client.get('/dispatch/pool-recurring', { params: { min_days: 3 } })
    recurring.value = data.pairs
  } finally {
    recurringLoading.value = false
  }
}
onMounted(loadRecurring)

const fleet = ref('大豐')
const date = ref('')
const maxDetour = ref(15)
const loading = ref(false)
const error = ref('')
const result = ref(null)

// 單一車行，不需清單

const consenting = ref(null)
const toast = ref('')

async function run() {
  if (!date.value) { error.value = '請選擇日期'; return }
  loading.value = true; error.value = ''; result.value = null
  try {
    const { data } = await client.get('/dispatch/pool-suggest', {
      params: { service_date: date.value, fleet: fleet.value, max_detour_min: maxDetour.value },
    })
    result.value = data
  } catch (e) {
    error.value = e.response?.data?.detail || '查詢失敗'
  } finally {
    loading.value = false
  }
}

async function consentGroup(group, idx) {
  const ids = group.members.map((m) => m.order_id)
  consenting.value = idx
  try {
    const { data } = await client.post('/dispatch/pool-consent', { order_ids: ids, consent: true })
    toast.value = `已登錄 ${data.updated} 筆同意(${data.by});重算中…`
    await run()  // 重新試算,已同意組會反映進現況
  } catch (e) {
    error.value = e.response?.data?.detail || '登錄同意失敗'
  } finally {
    consenting.value = null
    setTimeout(() => { toast.value = '' }, 4000)
  }
}
</script>

<template>
  <p class="text-muted">
    雙跑排班(現況 vs 全允許共乘),找出<strong>值得徵詢同意</strong>的共乘組與可省車數。
    僅顯示繞路在容許範圍內的舒適組合;此頁唯讀,不影響派遣資料。
  </p>

  <!-- 常態共乘對(P3):一次徵長期同意 -->
  <div class="card shadow-sm mb-3 border-info">
    <div class="card-header bg-info-subtle d-flex justify-content-between align-items-center py-2">
      <span>🔁 常態共乘對(反覆同行 ≥ 3 日,適合一次徵長期同意)</span>
      <span v-if="recurringLoading" class="spinner-border spinner-border-sm"></span>
      <span v-else class="badge bg-info text-dark">{{ recurring.length }} 組</span>
    </div>
    <div class="table-responsive" style="max-height: 260px; overflow-y: auto">
      <table class="table table-sm table-striped mb-0 align-middle">
        <thead><tr><th>乘客 A</th><th>乘客 B</th><th>車行</th><th>同行天數</th><th>常見路線(例)</th></tr></thead>
        <tbody>
          <tr v-for="(p, i) in recurring" :key="i">
            <td class="fw-semibold">{{ p.passengers[0] }}</td>
            <td class="fw-semibold">{{ p.passengers[1] }}</td>
            <td>{{ p.fleet }}</td>
            <td><span class="badge bg-primary">{{ p.days }} 日</span></td>
            <td class="small text-muted">{{ (p.sample_pickup || '').slice(0, 16) }} → {{ (p.sample_dropoff || '').slice(0, 16) }}</td>
          </tr>
          <tr v-if="!recurring.length && !recurringLoading"><td colspan="5" class="text-center text-muted py-3">無常態共乘對</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card shadow-sm mb-3"><div class="card-body">
    <div class="row g-2 align-items-end">
      <!-- 車行固定大豐 -->
      <div class="col-6 col-md-3">
        <label class="form-label">服務日期</label>
        <input v-model="date" type="date" class="form-control" />
      </div>
      <div class="col-6 col-md-3">
        <label class="form-label">最大可接受繞路(分)</label>
        <input v-model.number="maxDetour" type="number" min="0" class="form-control" />
      </div>
      <div class="col-6 col-md-3">
        <button class="btn btn-primary w-100" :disabled="loading" @click="run">
          <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>查詢建議
        </button>
      </div>
    </div>
  </div></div>

  <div v-if="error" class="alert alert-danger">{{ error }}</div>
  <div v-if="toast" class="alert alert-success py-2">{{ toast }}</div>

  <template v-if="result">
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="h3 mb-0">{{ result.vehicles_now }} → <span class="text-success">{{ result.vehicles_if_pooled }}</span></div>
        <small class="text-muted">用車:現況 → 共乘後</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm border-success"><div class="card-body py-3">
        <div class="display-6 fw-bold text-success">{{ result.vehicles_saved }}</div>
        <small class="text-muted">可省車數</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-primary">{{ result.groups_to_ask }}</div>
        <small class="text-muted">建議徵詢組數</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold">{{ result.n_orders }}</div>
        <small class="text-muted">當日成行單</small></div></div></div>
    </div>
    <p class="small text-muted">
      共找到 {{ result.groups_total }} 組可共乘,其中 {{ result.groups_comfortable }} 組繞路 ≤ {{ result.max_detour_min }} 分;
      下列 {{ result.groups_to_ask }} 組含尚未同意者,建議行控徵詢。
    </p>

    <div v-if="!result.suggestions.length" class="alert alert-secondary">當日無建議徵詢的共乘組。</div>

    <div v-for="(g, i) in result.suggestions" :key="i" class="card mb-2 shadow-sm">
      <div class="card-header d-flex justify-content-between align-items-center py-2">
        <span>共乘組 #{{ i + 1 }}（{{ g.size }} 趟）</span>
        <div class="d-flex align-items-center gap-2">
          <span class="badge" :class="g.max_detour_min <= 10 ? 'bg-success' : 'bg-warning text-dark'">最大繞路 {{ g.max_detour_min }} 分</span>
          <button class="btn btn-sm btn-success" :disabled="consenting === i" @click="consentGroup(g, i)">
            <span v-if="consenting === i" class="spinner-border spinner-border-sm me-1"></span>標記同意並重算
          </button>
        </div>
      </div>
      <ul class="list-group list-group-flush">
        <li v-for="m in g.members" :key="m.order_id" class="list-group-item d-flex justify-content-between align-items-center">
          <div>
            <span class="fw-semibold">{{ m.passenger || ('#' + m.order_id) }}</span>
            <span class="badge bg-light text-dark ms-1">{{ m.pax }} 人</span>
            <span v-if="m.welfare" class="badge bg-warning text-dark ms-1">福祉</span>
            <span v-if="m.already_consented" class="badge bg-success ms-1">已同意</span>
            <div class="small text-muted">{{ m.pickup }} → {{ m.dropoff }}</div>
          </div>
          <span class="text-muted small text-nowrap">繞 {{ m.detour_min }} 分</span>
        </li>
      </ul>
    </div>
  </template>
</template>
