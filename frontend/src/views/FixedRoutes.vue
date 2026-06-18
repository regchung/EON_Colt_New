<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'

const rows = ref([])
const matchDate = ref(new Date().toISOString().slice(0, 10))
const match = ref(null)
async function runMatch() {
  const { data } = await client.get('/fixed-routes/match', { params: { service_date: matchDate.value } })
  match.value = data
}
const error = ref('')
const toast = ref('')
const TIME_SLOTS = ['全天', '早', '午', '午後', '早晚']
const MATCH_FIELDS = [
  { v: 'any', t: '任意欄位' }, { v: 'passenger', t: '乘客姓名' }, { v: 'address', t: '地址/補充' },
]
const blank = () => ({ id: null, label: '', keyword: '', driver_name: '', time_slot: '全天', match_field: 'any', fleet: '', note: '', active: true })
const form = ref(blank())

function flash(m) { toast.value = m; setTimeout(() => { toast.value = '' }, 3000) }

async function load() {
  const { data } = await client.get('/fixed-routes/with-status')
  rows.value = data
}
onMounted(load)

function edit(r) {
  form.value = { ...r, fleet: r.fleet || '', note: r.note || '' }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function reset() { form.value = blank() }

async function save() {
  error.value = ''
  if (!form.value.label || !form.value.keyword || !form.value.driver_name) {
    error.value = '路線名稱、匹配關鍵字、指定司機為必填'; return
  }
  const body = {
    label: form.value.label, keyword: form.value.keyword, driver_name: form.value.driver_name,
    time_slot: form.value.time_slot, match_field: form.value.match_field,
    fleet: form.value.fleet || null, note: form.value.note || null, active: form.value.active,
  }
  try {
    if (form.value.id) await client.put(`/fixed-routes/${form.value.id}`, body)
    else await client.post('/fixed-routes', body)
    flash('已儲存'); reset(); await load()
  } catch (e) { error.value = e.response?.data?.detail || '儲存失敗' }
}
async function del(r) {
  if (!confirm(`刪除固定行程「${r.label} → ${r.driver_name}」?`)) return
  await client.delete(`/fixed-routes/${r.id}`); flash('已刪除'); await load()
}
</script>

<template>
  <p class="text-muted small">
    固定行程指定司機:設定「某地點/個案(關鍵字)固定由某司機執行」,可分早/午/晚時段。
    派遣時將符合的訂單優先指派給指定司機(整合中)。
  </p>
  <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
  <div v-if="toast" class="alert alert-success py-2">{{ toast }}</div>

  <!-- 新增 / 編輯 -->
  <div class="card shadow-sm mb-3"><div class="card-body">
    <div class="fw-semibold mb-2">{{ form.id ? '編輯固定行程 #' + form.id : '新增固定行程' }}</div>
    <div class="row g-2">
      <div class="col-6 col-md-2"><label class="form-label small mb-0">路線名稱</label>
        <input v-model="form.label" class="form-control form-control-sm" placeholder="成德國中-2" /></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">匹配關鍵字</label>
        <input v-model="form.keyword" class="form-control form-control-sm" placeholder="成德國中 / 錸工廠 / 向怡" /></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">指定司機</label>
        <input v-model="form.driver_name" class="form-control form-control-sm" placeholder="吳奇龍" /></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">時段</label>
        <select v-model="form.time_slot" class="form-select form-select-sm">
          <option v-for="t in TIME_SLOTS" :key="t" :value="t">{{ t }}</option></select></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">匹配欄位</label>
        <select v-model="form.match_field" class="form-select form-select-sm">
          <option v-for="m in MATCH_FIELDS" :key="m.v" :value="m.v">{{ m.t }}</option></select></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">車行(選填)</label>
        <input v-model="form.fleet" class="form-control form-control-sm" placeholder="新北" /></div>
      <div class="col-12 col-md-8"><label class="form-label small mb-0">備註</label>
        <input v-model="form.note" class="form-control form-control-sm" /></div>
      <div class="col-6 col-md-2 d-flex align-items-end">
        <div class="form-check"><input v-model="form.active" type="checkbox" class="form-check-input" id="act" />
          <label class="form-check-label small" for="act">啟用</label></div></div>
      <div class="col-6 col-md-2 d-flex align-items-end gap-2">
        <button class="btn btn-sm btn-primary" @click="save">{{ form.id ? '更新' : '新增' }}</button>
        <button v-if="form.id" class="btn btn-sm btn-outline-secondary" @click="reset">取消</button></div>
    </div>
  </div></div>

  <!-- 比對某日訂單 -->
  <div class="card shadow-sm mb-3 border-info"><div class="card-body">
    <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
      <span class="fw-semibold">🔎 比對某日訂單</span>
      <input v-model="matchDate" type="date" class="form-control form-control-sm" style="width:160px" />
      <button class="btn btn-sm btn-info text-dark" @click="runMatch">比對</button>
      <span v-if="match" class="small text-muted">符合 {{ match.matched }} 單,其中可派(司機有車) {{ match.pinnable }} 單</span>
    </div>
    <div v-if="match">
      <div v-if="match.unresolved_rules.length" class="alert alert-warning py-2 small mb-2">
        ⚠️ 有匹配但司機無車(需到「司機車輛」補):
        <span v-for="u in match.unresolved_rules" :key="u.driver_name" class="badge bg-warning text-dark me-1">{{ u.label }}→{{ u.driver_name }}</span>
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle small mb-0">
          <thead class="table-light"><tr><th>時間</th><th>路線</th><th>指定司機</th><th>可派車</th><th>乘客</th><th>路線</th></tr></thead>
          <tbody>
            <tr v-for="(it, i) in match.items" :key="i">
              <td class="text-nowrap">{{ it.time }}</td>
              <td>{{ it.label }}</td><td>{{ it.driver_name }}</td>
              <td><span :class="it.resolvable ? 'badge bg-success' : 'badge bg-danger'">{{ it.plate || '無車' }}</span></td>
              <td>{{ it.passenger }}</td>
              <td class="text-muted">{{ it.pickup }} → {{ it.dropoff }}</td>
            </tr>
            <tr v-if="!match.items.length"><td colspan="6" class="text-center text-muted py-2">該日無符合固定行程的訂單</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div></div>

  <!-- 清單 -->
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead class="table-light"><tr>
        <th>路線</th><th>關鍵字</th><th>指定司機</th><th>對應車</th><th>時段</th><th>匹配欄位</th><th>車行</th><th>啟用</th><th></th>
      </tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td class="fw-semibold">{{ r.label }}</td>
          <td><code>{{ r.keyword }}</code></td>
          <td>{{ r.driver_name }}</td>
          <td>
            <span v-if="r.driver_has_vehicle" class="badge bg-success">{{ r.driver_plate }}</span>
            <span v-else class="badge bg-danger" title="此司機在系統無車,需補建">無車</span>
          </td>
          <td>{{ r.time_slot }}</td>
          <td class="small text-muted">{{ MATCH_FIELDS.find(m => m.v === r.match_field)?.t || r.match_field }}</td>
          <td class="small">{{ r.fleet || '—' }}</td>
          <td>{{ r.active ? '✓' : '✗' }}</td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-outline-primary" @click="edit(r)">編輯</button>
            <button class="btn btn-sm btn-outline-danger ms-1" @click="del(r)">刪</button>
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="9" class="text-center text-muted py-3">尚無固定行程</td></tr>
      </tbody>
    </table>
  </div>
  <p class="small text-muted">
    🔴「無車」表示該司機在系統內尚無對應車輛,需先到車輛/名冊建立,固定行程才能實際派遣。
  </p>
</template>
