<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const WD = ['一', '二', '三', '四', '五', '六', '日']  // 0=Mon … 6=Sun

const patterns = ref([])
const loading = ref(false)
const error = ref('')
const toast = ref('')
const savingId = ref(null)

const exceptions = ref([])
const exForm = ref({ vehicle_id: null, ex_date: '', available: false, reason: '' })

const checkDate = ref('')
const availability = ref(null)

// 需求預測(weekday 基線)→ 建議排車
const fleets = ['台北', '新北', '神同行', '基隆', '樂格適', '發隆興']
const demandFleet = ref('台北')
const demand = ref(null)
async function loadDemand() {
  const { data } = await client.get('/dispatch/demand-forecast', {
    params: { fleet: demandFleet.value, lookback_weeks: 12 },
  })
  demand.value = data
}

function flash(m) { toast.value = m; setTimeout(() => { toast.value = '' }, 3000) }

async function loadPatterns() {
  loading.value = true; error.value = ''
  try {
    const { data } = await client.get('/roster/patterns')
    patterns.value = data.map((p) => ({ ...p, set: new Set(p.weekdays) }))
  } catch (e) {
    error.value = e.response?.data?.detail || '讀取失敗(需派遣員以上)'
  } finally {
    loading.value = false
  }
}
async function loadExceptions() {
  const { data } = await client.get('/roster/exceptions')
  exceptions.value = data
}
onMounted(async () => { await loadPatterns(); await loadExceptions(); await loadDemand() })

function toggle(p, wd) { p.set.has(wd) ? p.set.delete(wd) : p.set.add(wd) }

async function savePattern(p) {
  savingId.value = p.vehicle_id
  try {
    await client.put(`/roster/patterns/${p.vehicle_id}`, { weekdays: [...p.set] })
    flash(`已儲存 ${p.plate} 班表`)
  } catch (e) { error.value = e.response?.data?.detail || '儲存失敗' } finally { savingId.value = null }
}

async function addException() {
  if (!exForm.value.vehicle_id || !exForm.value.ex_date) { error.value = '請選車輛與日期'; return }
  try {
    await client.post('/roster/exceptions', exForm.value)
    exForm.value = { vehicle_id: null, ex_date: '', available: false, reason: '' }
    await loadExceptions(); flash('已新增例外')
  } catch (e) { error.value = e.response?.data?.detail || '新增失敗' }
}
async function delException(id) {
  await client.delete(`/roster/exceptions/${id}`); await loadExceptions(); flash('已刪除例外')
}

async function checkAvailability() {
  if (!checkDate.value) return
  const { data } = await client.get('/roster/availability', { params: { service_date: checkDate.value } })
  availability.value = data
}
async function seedFromHistory() {
  if (!confirm('從歷史回推會覆寫現有週期班表,確定?')) return
  const { data } = await client.post('/roster/seed-from-history?min_times=3')
  await loadPatterns(); flash(`已回推 ${data.patterns_created} 筆、涵蓋 ${data.vehicles_covered} 台`)
}
</script>

<template>
  <p class="text-muted">
    班表決定「當日哪些車有出勤」,即時派遣只會用出勤的車(無班表資料的車保守視為不出勤)。
    週期班表設常態上班日;單日請假/維修/加班用「例外」。
  </p>

  <div v-if="error" class="alert alert-danger">{{ error }}</div>
  <div v-if="toast" class="alert alert-success py-2">{{ toast }}</div>

  <!-- 當日出勤查詢 -->
  <div class="card shadow-sm mb-3"><div class="card-body d-flex flex-wrap align-items-end gap-2">
    <div><label class="form-label mb-0 small">查某日出勤</label>
      <input v-model="checkDate" type="date" class="form-control form-control-sm" /></div>
    <button class="btn btn-sm btn-primary" @click="checkAvailability">查詢</button>
    <span v-if="availability" class="ms-2">{{ availability.service_date }} 出勤
      <span class="badge bg-success">{{ availability.count }}</span> 台</span>
    <button v-if="auth.isAdmin" class="btn btn-sm btn-outline-secondary ms-auto" @click="seedFromHistory">
      從歷史回推週期班表
    </button>
  </div></div>

  <!-- 需求預測(建議排車) -->
  <div class="card shadow-sm mb-3 border-info">
    <div class="card-header bg-info-subtle d-flex justify-content-between align-items-center py-2">
      <span>📈 需求預測(weekday 基線 → 建議排車數)</span>
      <select v-model="demandFleet" class="form-select form-select-sm" style="width:auto" @change="loadDemand">
        <option v-for="f in fleets" :key="f" :value="f">{{ f }}</option>
      </select>
    </div>
    <div class="table-responsive">
      <table v-if="demand" class="table table-sm text-center align-middle mb-0">
        <thead><tr><th></th><th v-for="r in demand.weekday_profile" :key="r.weekday">{{ r.name }}</th></tr></thead>
        <tbody>
          <tr><td class="text-start fw-semibold">平均趟次</td>
            <td v-for="r in demand.weekday_profile" :key="r.weekday">{{ r.avg_trips }}</td></tr>
          <tr><td class="text-start fw-semibold">建議排車</td>
            <td v-for="r in demand.weekday_profile" :key="r.weekday">
              <span class="badge" :class="r.suggest_vehicles ? 'bg-info text-dark' : 'bg-light text-muted'">{{ r.suggest_vehicles }}</span></td></tr>
        </tbody>
      </table>
    </div>
    <div class="card-footer small text-muted py-1">
      依近 {{ demand?.lookback_weeks }} 週同星期平均;設定下方週期班表時可參考此建議數。
    </div>
  </div>

  <!-- 週期班表 -->
  <div class="card shadow-sm mb-3">
    <div class="card-header py-2 fw-semibold">週期班表(勾選常態上班日)</div>
    <div class="table-responsive" style="max-height: 460px; overflow-y: auto">
      <table class="table table-sm align-middle mb-0">
        <thead class="table-light" style="position: sticky; top: 0">
          <tr><th>車牌</th><th>車行</th><th v-for="(d, i) in WD" :key="i" class="text-center">{{ d }}</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="p in patterns" :key="p.vehicle_id">
            <td class="fw-semibold">{{ p.plate }}</td>
            <td class="small text-muted">{{ p.home_fleet }}</td>
            <td v-for="(d, i) in WD" :key="i" class="text-center">
              <input type="checkbox" :checked="p.set.has(i)" @change="toggle(p, i)" />
            </td>
            <td><button class="btn btn-sm btn-outline-primary" :disabled="savingId === p.vehicle_id" @click="savePattern(p)">
              <span v-if="savingId === p.vehicle_id" class="spinner-border spinner-border-sm"></span><span v-else>存</span>
            </button></td>
          </tr>
          <tr v-if="!patterns.length && !loading"><td colspan="10" class="text-center text-muted py-3">尚無車輛</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 例外 -->
  <div class="card shadow-sm">
    <div class="card-header py-2 fw-semibold">單日例外(請假/維修/臨時加班)</div>
    <div class="card-body">
      <div class="row g-2 align-items-end mb-3">
        <div class="col-6 col-md-3"><label class="form-label small">車輛</label>
          <select v-model.number="exForm.vehicle_id" class="form-select form-select-sm">
            <option :value="null">選車輛</option>
            <option v-for="p in patterns" :key="p.vehicle_id" :value="p.vehicle_id">{{ p.plate }}</option>
          </select></div>
        <div class="col-6 col-md-3"><label class="form-label small">日期</label>
          <input v-model="exForm.ex_date" type="date" class="form-control form-control-sm" /></div>
        <div class="col-6 col-md-2"><label class="form-label small">當日</label>
          <select v-model="exForm.available" class="form-select form-select-sm">
            <option :value="false">不出勤(請假/維修)</option>
            <option :value="true">臨時加班</option>
          </select></div>
        <div class="col-6 col-md-2"><label class="form-label small">原因</label>
          <input v-model="exForm.reason" class="form-control form-control-sm" /></div>
        <div class="col-12 col-md-2"><button class="btn btn-sm btn-primary w-100" @click="addException">新增例外</button></div>
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle mb-0">
          <thead><tr><th>日期</th><th>車牌</th><th>狀態</th><th>原因</th><th></th></tr></thead>
          <tbody>
            <tr v-for="e in exceptions" :key="e.id">
              <td>{{ e.ex_date }}</td><td>{{ e.plate }}</td>
              <td><span class="badge" :class="e.available ? 'bg-success' : 'bg-secondary'">{{ e.available ? '加班' : '不出勤' }}</span></td>
              <td class="small text-muted">{{ e.reason }}</td>
              <td><button class="btn btn-sm btn-outline-danger" @click="delException(e.id)">刪</button></td>
            </tr>
            <tr v-if="!exceptions.length"><td colspan="5" class="text-center text-muted py-3">尚無例外</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
