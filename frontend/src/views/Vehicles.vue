<script setup>
import { onMounted, ref, reactive } from 'vue'
import { useVehiclesStore } from '../stores/vehicles'
import client from '../api/client'

const store = useVehiclesStore()

// --- 車隊名冊匯入 ---
const fileInput = ref(null)
const importing = ref(false)
const importResult = ref(null)
const importError = ref('')

async function uploadFleet(e) {
  const f = e.target.files?.[0]
  if (!f) return
  importing.value = true
  importResult.value = null
  importError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', f)
    const { data } = await client.post('/fleet/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    importResult.value = data
    await store.fetchAll()
  } catch (err) {
    importError.value = err.response?.data?.detail || '匯入失敗'
  } finally {
    importing.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

// --- 名冊對帳(不在檔內→停派)---
const reconcileInput = ref(null)
const reconcileResult = ref(null)
async function uploadReconcile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  reconcileResult.value = null
  importError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', f)
    const { data } = await client.post('/fleet/reconcile', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    reconcileResult.value = data
    await store.fetchAll()
  } catch (err) {
    importError.value = err.response?.data?.detail || '對帳失敗'
  } finally {
    if (reconcileInput.value) reconcileInput.value.value = ''
  }
}

async function toggleSuspend(v) {
  await client.post(`/vehicles/${v.id}/suspend`, null, { params: { value: !v.suspended } })
  await store.fetchAll()
}

const blank = () => ({
  plate: '',
  type: 'normal',
  seats: 4,
  wheelchair: 0,
  shift_start: '08:00',
  shift_end: '18:00',
  depot_lng: null,
  depot_lat: null,
  active: true,
})

const showForm = ref(false)
const editingId = ref(null)
const form = reactive(blank())

onMounted(() => store.fetchAll())

function openCreate() {
  Object.assign(form, blank())
  editingId.value = null
  showForm.value = true
}
function openEdit(v) {
  Object.assign(form, {
    ...v,
    shift_start: v.shift_start?.slice(0, 5) || '',
    shift_end: v.shift_end?.slice(0, 5) || '',
  })
  editingId.value = v.id
  showForm.value = true
}
async function save() {
  const payload = { ...form }
  if (editingId.value) await store.update(editingId.value, payload)
  else await store.create(payload)
  showForm.value = false
}
async function remove(v) {
  if (confirm(`確定刪除車輛 ${v.plate || v.id}?`)) await store.remove(v.id)
}
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3">
    <span class="text-muted">共 {{ store.items.length }} 台</span>
    <div class="d-flex gap-2">
      <button class="btn btn-outline-success" :disabled="importing"
              @click="fileInput?.click()">
        <span v-if="importing" class="spinner-border spinner-border-sm me-1"></span>
        匯入車隊名冊
      </button>
      <input ref="fileInput" type="file" accept=".xls,.xlsx" class="d-none" @change="uploadFleet" />
      <button class="btn btn-outline-danger" @click="reconcileInput?.click()" title="不在名冊中的車輛/司機改為停派">
        依名冊對帳
      </button>
      <input ref="reconcileInput" type="file" accept=".xls,.xlsx" class="d-none" @change="uploadReconcile" />
      <button class="btn btn-primary" @click="openCreate">+ 新增車輛</button>
    </div>
  </div>

  <p class="small text-muted mb-3">
    「匯入車隊名冊」可上傳司機/車輛主檔(.xls/.xlsx),回填真實可載客數、福祉能力,
    以及<strong>出車起點/收車終點</strong>(以車牌冪等;排班會讓每車首站自起點出發、末站返回終點)。
  </p>

  <div v-if="importError" class="alert alert-danger">{{ importError }}</div>
  <div v-if="importResult" class="alert alert-success">
    匯入完成:車輛 新增 {{ importResult.vehicles_created }} / 更新 {{ importResult.vehicles_updated }};
    司機 新增 {{ importResult.drivers_created }} / 更新 {{ importResult.drivers_updated }};
    福祉 {{ importResult.welfare }} / 一般 {{ importResult.normal }}
    <span v-if="importResult.errors?.length" class="text-danger">;錯誤 {{ importResult.errors.length }} 列</span>
  </div>

  <div v-if="reconcileResult" class="alert alert-warning">
    對帳完成(名冊內車牌 {{ reconcileResult.file_plates }} / 司機 {{ reconcileResult.file_names }}):
    車輛 停派 +{{ reconcileResult.vehicles_suspended }} / 啟用 +{{ reconcileResult.vehicles_activated }};
    司機 停派 +{{ reconcileResult.drivers_suspended }} / 啟用 +{{ reconcileResult.drivers_activated }};
    車輛座位/輪椅數更新 {{ reconcileResult.vehicles_specs_updated }} 台。停派者不納入自動派遣。
  </div>

  <div v-if="store.error" class="alert alert-danger">{{ store.error }}</div>

  <!-- 表單面板 -->
  <div v-if="showForm" class="card shadow-sm mb-3">
    <div class="card-header">{{ editingId ? '編輯車輛' : '新增車輛' }}</div>
    <div class="card-body">
      <div class="row g-3">
        <div class="col-12 col-md-4">
          <label class="form-label">車牌</label>
          <input v-model="form.plate" class="form-control" placeholder="ABC-1234" />
        </div>
        <div class="col-6 col-md-4">
          <label class="form-label">車種</label>
          <select v-model="form.type" class="form-select">
            <option value="normal">一般車</option>
            <option value="welfare">福祉車</option>
          </select>
        </div>
        <div class="col-6 col-md-2">
          <label class="form-label">座位數</label>
          <input v-model.number="form.seats" type="number" min="1" class="form-control" />
        </div>
        <div class="col-6 col-md-2">
          <label class="form-label">輪椅數</label>
          <input v-model.number="form.wheelchair" type="number" min="0" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">班別開始</label>
          <input v-model="form.shift_start" type="time" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">班別結束</label>
          <input v-model="form.shift_end" type="time" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">出車點經度</label>
          <input v-model.number="form.depot_lng" type="number" step="any" class="form-control" />
        </div>
        <div class="col-6 col-md-3">
          <label class="form-label">出車點緯度</label>
          <input v-model.number="form.depot_lat" type="number" step="any" class="form-control" />
        </div>
        <div class="col-12">
          <div class="form-check">
            <input v-model="form.active" class="form-check-input" type="checkbox" id="vActive" />
            <label class="form-check-label" for="vActive">啟用中</label>
          </div>
        </div>
      </div>
    </div>
    <div class="card-footer text-end">
      <button class="btn btn-secondary me-2" @click="showForm = false">取消</button>
      <button class="btn btn-primary" @click="save">儲存</button>
    </div>
  </div>

  <!-- 列表 -->
  <div class="table-responsive">
    <table class="table table-striped table-hover align-middle">
      <thead>
        <tr>
          <th>#</th><th>車牌</th><th>車種</th><th>座位/輪椅</th><th>起訖點</th><th>班別</th><th>狀態</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in store.items" :key="v.id">
          <td>{{ v.id }}</td>
          <td>{{ v.plate || '-' }}</td>
          <td>
            <span class="badge" :class="v.type === 'welfare' ? 'bg-warning text-dark' : 'bg-secondary'">
              {{ v.type === 'welfare' ? '福祉車' : '一般車' }}
            </span>
          </td>
          <td>{{ v.seats }} 座<span v-if="v.wheelchair" class="text-info"> · ♿{{ v.wheelchair }}</span></td>
          <td>
            <span v-if="v.start_lng != null" class="badge bg-info text-dark"
                  :title="`起 ${v.start_lng?.toFixed(4)},${v.start_lat?.toFixed(4)} / 訖 ${v.end_lng?.toFixed(4)},${v.end_lat?.toFixed(4)}`">已設</span>
            <span v-else class="text-muted">—</span>
          </td>
          <td>{{ (v.shift_start || '').slice(0,5) }} ~ {{ (v.shift_end || '').slice(0,5) }}</td>
          <td>
            <span v-if="v.suspended" class="badge bg-danger">停派</span>
            <span v-else class="badge" :class="v.active ? 'bg-success' : 'bg-secondary'">
              {{ v.active ? '啟用' : '停用' }}
            </span>
          </td>
          <td class="text-nowrap">
            <button class="btn btn-sm me-1" :class="v.suspended ? 'btn-outline-success' : 'btn-outline-warning'"
                    @click="toggleSuspend(v)">{{ v.suspended ? '啟用' : '停派' }}</button>
            <button class="btn btn-sm btn-outline-primary me-1" @click="openEdit(v)">編輯</button>
            <button class="btn btn-sm btn-outline-danger" @click="remove(v)">刪除</button>
          </td>
        </tr>
        <tr v-if="!store.items.length">
          <td colspan="8" class="text-center text-muted py-4">尚無車輛,點右上角新增。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
