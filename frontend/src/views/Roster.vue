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
const demandFleet = ref('大豐')
const demand = ref(null)
const applying = ref(false)
const applyResult = ref(null)
async function loadDemand() {
  applyResult.value = null
  const { data } = await client.get('/dispatch/demand-forecast', {
    params: { fleet: demandFleet.value, lookback_weeks: 12 },
  })
  demand.value = data
}
async function applyForecast() {
  if (!confirm(`將以建議排車數覆寫「${demandFleet.value}」車行的週期班表,各日挑歷史最常出勤的前 N 台。確定套用?`)) return
  applying.value = true
  try {
    const { data } = await client.post('/roster/apply-forecast', null, {
      params: { fleet: demandFleet.value, lookback_weeks: 12, dry_run: false },
    })
    if (!data.applied) { error.value = data.reason || '無法套用'; return }
    applyResult.value = data
    await loadPatterns()
    const short = data.plan.filter((p) => p.short > 0)
    flash(`已套用 ${demandFleet.value}:設定 ${data.patterns_set} 筆班表` +
      (short.length ? `;${short.length} 個工作日歷史車數不足建議` : ''))
  } catch (e) {
    error.value = e.response?.data?.detail || '套用失敗'
  } finally {
    applying.value = false
  }
}

function flash(m) { toast.value = m; setTimeout(() => { toast.value = '' }, 3000) }

// 自然語言出勤解析(主題2)
const attText = ref('')
const attDate = ref(new Date().toISOString().slice(0, 10))
const attPreview = ref(null)
const attLoading = ref(false)
async function parseAtt() {
  if (!attText.value.trim()) { error.value = '請貼上出勤異動文字'; return }
  attLoading.value = true; error.value = ''; attPreview.value = null
  try {
    const { data } = await client.post('/roster/parse-attendance',
      { text: attText.value, service_date: attDate.value }, { timeout: 90000 })
    attPreview.value = data
  } catch (e) { error.value = e.response?.data?.detail || '解析失敗(需設定 Claude 金鑰)' } finally { attLoading.value = false }
}
async function applyAtt() {
  const items = (attPreview.value?.items || []).filter((i) => i.applicable).map((i) => ({
    vehicle_id: i.vehicle_id, available: i.available,
    shift_start: i.shift_start, shift_end: i.shift_end, reason: i.reason || i.status,
  }))
  if (!items.length) { error.value = '無可套用項目'; return }
  try {
    const { data } = await client.post('/roster/apply-attendance', { service_date: attDate.value, items })
    flash(`已套用 ${data.applied} 筆出勤異動到 ${attDate.value}`)
    attPreview.value = null; attText.value = ''
    await loadExceptions()
  } catch (e) { error.value = e.response?.data?.detail || '套用失敗' }
}

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
    await client.put(`/roster/patterns/${p.vehicle_id}`, {
      weekdays: [...p.set],
      shift_start: p.shift_start || null,
      shift_end: p.shift_end || null,
    })
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

  <!-- 自然語言出勤異動 -->
  <div class="card shadow-sm mb-3 border-success">
    <div class="card-header bg-success-subtle py-2 fw-semibold">🗣️ 貼上出勤異動(自動解析)</div>
    <div class="card-body">
      <div class="d-flex flex-wrap align-items-end gap-2 mb-2">
        <div><label class="form-label small mb-0">套用日期</label>
          <input v-model="attDate" type="date" class="form-control form-control-sm" style="width:160px" /></div>
        <button class="btn btn-sm btn-success" :disabled="attLoading" @click="parseAtt">
          <span v-if="attLoading" class="spinner-border spinner-border-sm me-1"></span>解析
        </button>
        <span class="small text-muted">例:「休3人:朱正元、張啟明、温智祥」「梁銘漢8:00-11:00不排,11:00可接」</span>
      </div>
      <textarea v-model="attText" class="form-control form-control-sm mb-2" rows="3"
                placeholder="直接貼上行控的出勤調整文字…"></textarea>
      <div v-if="attPreview">
        <div v-if="attPreview.errors?.length" class="alert alert-warning py-1 small mb-2">
          <div v-for="(e, i) in attPreview.errors" :key="i">⚠️ {{ e }}</div>
        </div>
        <table v-if="attPreview.items?.length" class="table table-sm align-middle small mb-2">
          <thead class="table-light"><tr><th>司機</th><th>異動</th><th>時段</th><th>對應車</th><th>套用</th></tr></thead>
          <tbody>
            <tr v-for="(it, i) in attPreview.items" :key="i">
              <td>{{ it.driver }}</td>
              <td><span class="badge" :class="it.available ? 'bg-info text-dark' : 'bg-secondary'">{{ it.status }}</span></td>
              <td>{{ it.shift_start ? ('起 ' + it.shift_start) : '' }}{{ it.shift_end ? (' 迄 ' + it.shift_end) : '' }}<span v-if="!it.shift_start && !it.shift_end" class="text-muted">—</span></td>
              <td><span :class="it.applicable ? 'badge bg-success' : 'badge bg-danger'">{{ it.plate || '無車' }}</span></td>
              <td>{{ it.applicable ? '✓' : '✗' }}</td>
            </tr>
          </tbody>
        </table>
        <button class="btn btn-sm btn-primary" @click="applyAtt">套用到班表例外</button>
      </div>
    </div>
  </div>

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
    <div class="card-header bg-info-subtle d-flex flex-wrap justify-content-between align-items-center gap-2 py-2">
      <span>📈 需求預測(weekday 基線 → 建議排車數)</span>
      <div class="d-flex align-items-center gap-2">
        <span class="badge bg-primary">大豐</span>
        <button class="btn btn-sm btn-info text-dark" :disabled="applying" @click="applyForecast">
          <span v-if="applying" class="spinner-border spinner-border-sm me-1"></span>套用建議到班表
        </button>
      </div>
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
          <tr v-if="applyResult"><td class="text-start fw-semibold">實派(已套用)</td>
            <td v-for="p in applyResult.plan" :key="p.weekday">
              <span :class="p.short ? 'text-danger fw-bold' : ''">{{ p.assigned }}</span>
              <small v-if="p.short" class="text-danger">(缺{{ p.short }})</small></td></tr>
        </tbody>
      </table>
    </div>
    <div class="card-footer small text-muted py-1">
      依近 {{ demand?.lookback_weeks }} 週同星期平均。「套用建議到班表」會以各日建議數,挑該車行歷史最常出勤的前 N 台覆寫此車行週期班表;
      若歷史可用車數不足建議,顯示缺口(可手動於下方補上班日)。
    </div>
  </div>

  <!-- 週期班表 -->
  <div class="card shadow-sm mb-3">
    <div class="card-header py-2">
      <span class="fw-semibold">週期班表(勾選常態上班日)</span>
      <small class="text-muted ms-2">起/迄為該車班別時段(套用所有上班日);留空則用服務時段預設(06–18)。即時派遣會以此限制出車時間窗。</small>
    </div>
    <div class="table-responsive" style="max-height: 460px; overflow-y: auto">
      <table class="table table-sm align-middle mb-0">
        <thead class="table-light" style="position: sticky; top: 0">
          <tr><th>車牌</th><th>車行</th><th v-for="(d, i) in WD" :key="i" class="text-center">{{ d }}</th><th class="text-center">起</th><th class="text-center">迄</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="p in patterns" :key="p.vehicle_id">
            <td class="fw-semibold">{{ p.plate }}</td>
            <td class="small text-muted">{{ p.home_fleet }}</td>
            <td v-for="(d, i) in WD" :key="i" class="text-center">
              <input type="checkbox" :checked="p.set.has(i)" @change="toggle(p, i)" />
            </td>
            <td><input v-model="p.shift_start" type="time" class="form-control form-control-sm" style="width:7.5rem" /></td>
            <td><input v-model="p.shift_end" type="time" class="form-control form-control-sm" style="width:7.5rem" /></td>
            <td><button class="btn btn-sm btn-outline-primary" :disabled="savingId === p.vehicle_id" @click="savePattern(p)">
              <span v-if="savingId === p.vehicle_id" class="spinner-border spinner-border-sm"></span><span v-else>存</span>
            </button></td>
          </tr>
          <tr v-if="!patterns.length && !loading"><td colspan="12" class="text-center text-muted py-3">尚無車輛</td></tr>
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
