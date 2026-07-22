<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

const meta = ref({ fleets: [], min_date: null, max_date: null })
const date = ref('')
const fleet = ref('')
const plate = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')

async function loadMeta() {
  const { data: m } = await client.get('/dispatch/daily-tasks/meta')
  meta.value = m
  if (!date.value) date.value = m.max_date || new Date().toISOString().slice(0, 10)
}

async function load() {
  if (!date.value) return
  loading.value = true
  error.value = ''
  try {
    const params = { service_date: date.value, source: 'plan' }
    if (fleet.value) params.fleet = fleet.value
    if (plate.value.trim()) params.plate = plate.value.trim()
    const { data: d } = await client.get('/dispatch/daily-tasks', { params })
    data.value = d
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '查詢失敗'
  } finally {
    loading.value = false
  }
}

onMounted(async () => { await loadMeta(); await load() })
function printCards() { window.print() }
</script>

<template>
  <!-- 過濾列 -->
  <div class="card shadow-sm mb-3 no-print"><div class="card-body d-flex flex-wrap align-items-end gap-2">
    <div><label class="form-label mb-0 small">日期</label>
      <input v-model="date" type="date"
             class="form-control form-control-sm" style="width:160px" /></div>
    <div v-if="meta.fleets.length > 1"><label class="form-label mb-0 small">車行</label>
      <select v-model="fleet" class="form-select form-select-sm" style="width:140px">
        <option value="">全部車行</option>
        <option v-for="f in meta.fleets" :key="f" :value="f">{{ f }}</option>
      </select></div>
    <div><label class="form-label mb-0 small">車牌</label>
      <input v-model="plate" placeholder="如 RAS-1710" class="form-control form-control-sm" style="width:130px"
             @keyup.enter="load" /></div>
    <button class="btn btn-sm btn-primary" :disabled="loading" @click="load">{{ loading ? '查詢中…' : '查詢' }}</button>
    <button class="btn btn-sm btn-outline-secondary" :disabled="!data || !data.total_tasks" @click="printCards">🖨 列印口卡</button>
    <span v-if="data" class="ms-auto small text-muted">
      {{ data.service_date }}　出勤 <b>{{ data.total_vehicles }}</b> 車 ·
      任務 <b>{{ data.total_tasks }}</b> 趟
    </span>
  </div></div>

  <div v-if="error" class="alert alert-danger no-print">{{ error }}</div>

  <!-- 列印標題(僅列印時顯示) -->
  <div v-if="data" class="print-only mb-2">
    <h5 class="mb-0">每日車輛任務口卡　{{ data.service_date }}<span v-if="fleet"> · {{ fleet }}</span></h5>
  </div>

  <template v-if="data">
    <div v-for="f in data.fleets" :key="f.fleet" class="mb-3">
      <h6 class="text-primary border-bottom pb-1 mb-2">
        🚖 {{ f.fleet }}<span class="text-muted small ms-2">{{ f.vehicle_count }} 車 / {{ f.task_count }} 趟</span>
      </h6>
      <div class="row g-2">
        <div v-for="v in f.vehicles" :key="v.plate" class="col-12 col-lg-6">
          <div class="card shadow-sm h-100 kou-card">
            <div class="card-header py-2 d-flex justify-content-between align-items-center bg-light">
              <span><span class="fw-bold fs-6">{{ v.plate }}</span>
                <span class="text-muted ms-2">{{ v.driver || '—' }}</span>
                <span v-if="v.driver_phone" class="text-muted small ms-1">{{ v.driver_phone }}</span></span>
              <span class="small"><span class="badge bg-secondary">{{ v.task_count }} 趟</span>
                <span class="text-muted ms-1">{{ v.first }}–{{ v.last }}</span></span>
            </div>
            <div class="table-responsive">
              <table class="table table-sm mb-0 align-middle small">
                <thead class="table-light"><tr>
                  <th style="width:2rem">#</th><th style="width:3.2rem">時間</th><th>乘客 / 路線</th>
                  <th style="width:2rem" class="text-center">人</th><th style="width:3rem">標記</th>
                </tr></thead>
                <tbody>
                  <tr v-for="(t, i) in v.tasks" :key="i">
                    <td class="text-muted">{{ i + 1 }}</td>
                    <td class="fw-semibold text-nowrap">{{ t.time }}</td>
                    <td>
                      <div>
                        <span class="badge bg-secondary me-1" v-if="t.is_standby" style="font-size:.65rem">候補</span>
                        <span class="fw-semibold">{{ t.passenger || '—' }}</span>
                        <span v-if="t.phone" class="text-muted small ms-1">{{ t.phone }}</span>
                      </div>
                      <div class="text-muted" style="font-size:.8rem">{{ t.pickup }} <span class="text-success">→</span> {{ t.dropoff }}</div>
                    </td>
                    <td class="text-center">{{ t.pax }}</td>
                    <td>
                      <span v-if="t.welfare" class="badge bg-warning text-dark" title="福祉車">福</span>
                      <span v-if="t.wheelchair" class="badge bg-info text-dark" title="輪椅">♿{{ t.wheelchair }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="!data.fleets.length" class="text-center text-muted py-5">該日期 / 條件下無任務資料。</div>
  </template>
</template>

<style scoped>
.print-only { display: none; }
@media print {
  .no-print { display: none !important; }
  .print-only { display: block !important; }
  .kou-card { break-inside: avoid; page-break-inside: avoid; box-shadow: none !important; border: 1px solid #999; }
}
</style>
