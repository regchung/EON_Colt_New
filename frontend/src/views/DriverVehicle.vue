<script setup>
import { onMounted, ref, computed } from 'vue'
import client from '../api/client'

const data = ref({ count: 0, missing: 0, fixed_route_unresolved: [], drivers: [] })
const fleet = ref('')
const missingOnly = ref(false)
const search = ref('')
const error = ref('')
const toast = ref('')

// 指派車欄(每列暫存)
const edit = ref({})   // driver_id -> {plate, seats, type}
// 新增司機(補固定行程缺檔)
const nf = ref({ name: '', home_fleet: '', plate: '', seats: 4, type: 'normal' })

function flash(m) { toast.value = m; setTimeout(() => { toast.value = '' }, 3000) }

async function load() {
  const params = {}
  if (fleet.value) params.fleet = fleet.value
  if (missingOnly.value) params.missing_only = true
  const { data: d } = await client.get('/driver-vehicle', { params })
  data.value = d
  edit.value = {}
}
onMounted(load)

const filtered = computed(() => {
  const s = search.value.trim()
  return s ? data.value.drivers.filter((r) => (r.name || '').includes(s)) : data.value.drivers
})

function rowEdit(r) {
  return edit.value[r.driver_id] || (edit.value[r.driver_id] = { plate: r.plate || '', seats: r.seats || 4, type: r.vehicle_type || 'normal' })
}
async function assign(r) {
  const e = rowEdit(r)
  if (!e.plate.trim()) { error.value = '請輸入車牌'; return }
  error.value = ''
  try {
    const { data: res } = await client.post(`/driver-vehicle/${r.driver_id}/assign`,
      { plate: e.plate.trim(), seats: e.seats, type: e.type, fleet: r.home_fleet })
    flash(`${r.name} → ${res.plate}${res.vehicle_created ? '(新建車)' : ''}`)
    await load()
  } catch (err) { error.value = err.response?.data?.detail || '指派失敗' }
}
async function unassign(r) {
  if (!confirm(`解除 ${r.name} 的車輛對應?`)) return
  await client.delete(`/driver-vehicle/${r.driver_id}/assign`); flash('已解除'); await load()
}
function prefill(name) { nf.value.name = name; window.scrollTo({ top: 0, behavior: 'smooth' }) }
async function createDriver() {
  if (!nf.value.name.trim()) { error.value = '請輸入司機姓名'; return }
  error.value = ''
  try {
    await client.post('/driver-vehicle/create-driver', {
      name: nf.value.name.trim(), home_fleet: nf.value.home_fleet || null,
      plate: nf.value.plate || null, seats: nf.value.seats, type: nf.value.type,
    })
    flash(`已建立司機 ${nf.value.name}`); nf.value = { name: '', home_fleet: '', plate: '', seats: 4, type: 'normal' }
    await load()
  } catch (err) { error.value = err.response?.data?.detail || '建立失敗' }
}
</script>

<template>
  <p class="text-muted small">
    司機↔車輛對應(派遣/休假/固定行程的地基)。可為司機指派既有車或建新車;補齊固定行程引用但未建檔的司機。
  </p>
  <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
  <div v-if="toast" class="alert alert-success py-2">{{ toast }}</div>

  <!-- 固定行程未對應司機 -->
  <div v-if="data.fixed_route_unresolved.length" class="alert alert-warning">
    <b>⚠️ 固定行程引用但系統無車的司機({{ data.fixed_route_unresolved.length }}):</b>
    <span v-for="n in data.fixed_route_unresolved" :key="n" class="badge bg-warning text-dark me-1"
          style="cursor:pointer" @click="prefill(n)">{{ n }}（點此建檔）</span>
  </div>

  <!-- 新增司機 + 車 -->
  <div class="card shadow-sm mb-3"><div class="card-body">
    <div class="fw-semibold mb-2">新增司機(可一併建車)</div>
    <div class="row g-2 align-items-end">
      <div class="col-6 col-md-2"><label class="form-label small mb-0">姓名</label>
        <input v-model="nf.name" class="form-control form-control-sm" /></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">車行</label>
        <input v-model="nf.home_fleet" class="form-control form-control-sm" placeholder="台北" /></div>
      <div class="col-6 col-md-2"><label class="form-label small mb-0">車牌(選填)</label>
        <input v-model="nf.plate" class="form-control form-control-sm" placeholder="RXX-0000" /></div>
      <div class="col-4 col-md-1"><label class="form-label small mb-0">座位</label>
        <input v-model.number="nf.seats" type="number" min="1" class="form-control form-control-sm" /></div>
      <div class="col-4 col-md-2"><label class="form-label small mb-0">車種</label>
        <select v-model="nf.type" class="form-select form-select-sm">
          <option value="normal">一般車</option><option value="welfare">福祉車</option></select></div>
      <div class="col-4 col-md-2"><button class="btn btn-sm btn-primary w-100" @click="createDriver">新增司機</button></div>
    </div>
  </div></div>

  <!-- 過濾 -->
  <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
    <input v-model="search" class="form-control form-control-sm" style="width:160px" placeholder="搜尋姓名" />
    <input v-model="fleet" class="form-control form-control-sm" style="width:120px" placeholder="車行" @change="load" />
    <div class="form-check"><input v-model="missingOnly" type="checkbox" class="form-check-input" id="mo" @change="load" />
      <label class="form-check-label small" for="mo">只看無車</label></div>
    <span class="ms-auto small text-muted">司機 {{ data.count }} 人 · 無車 {{ data.missing }} 人</span>
  </div>

  <!-- 清單 -->
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead class="table-light"><tr>
        <th>司機</th><th>車行</th><th>目前車</th><th>指派/變更車輛</th><th></th>
      </tr></thead>
      <tbody>
        <tr v-for="r in filtered" :key="r.driver_id">
          <td class="fw-semibold">{{ r.name }} <span v-if="!r.active" class="badge bg-secondary">停用</span></td>
          <td class="small text-muted">{{ r.home_fleet || '—' }}</td>
          <td>
            <span v-if="r.has_vehicle" class="badge bg-success">{{ r.plate }}</span>
            <span v-else class="badge bg-danger">無車</span>
          </td>
          <td>
            <div class="d-flex gap-1">
              <input v-model="rowEdit(r).plate" class="form-control form-control-sm" style="width:8rem" placeholder="車牌" />
              <input v-model.number="rowEdit(r).seats" type="number" min="1" class="form-control form-control-sm" style="width:4rem" />
              <select v-model="rowEdit(r).type" class="form-select form-select-sm" style="width:6rem">
                <option value="normal">一般</option><option value="welfare">福祉</option></select>
              <button class="btn btn-sm btn-outline-primary" @click="assign(r)">指派</button>
            </div>
          </td>
          <td><button v-if="r.has_vehicle" class="btn btn-sm btn-outline-danger" @click="unassign(r)">解除</button></td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="5" class="text-center text-muted py-3">無司機</td></tr>
      </tbody>
    </table>
  </div>
</template>
