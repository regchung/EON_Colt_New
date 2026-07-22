<script setup>
import { onMounted, ref, reactive, computed, watch, nextTick } from 'vue'
import { useVehiclesStore } from '../stores/vehicles'
import client from '../api/client'
import Pagination from '../components/Pagination.vue'

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
  start_lng: null,
  start_lat: null,
  end_lng: null,
  end_lat: null,
  district: '',
  active: true,
})

// 新北市29行政區 + 行政中心座標 [lng, lat]
const NTPC_DISTRICT_COORDS = {
  '板橋區': [121.4628, 25.0136],
  '三重區': [121.4867, 25.0617],
  '中和區': [121.5030, 24.9986],
  '永和區': [121.5198, 25.0145],
  '新莊區': [121.4498, 25.0399],
  '新店區': [121.5415, 24.9723],
  '樹林區': [121.4222, 24.9939],
  '鶯歌區': [121.3475, 24.9555],
  '三峽區': [121.3720, 24.9365],
  '淡水區': [121.4512, 25.1695],
  '汐止區': [121.6557, 25.0637],
  '瑞芳區': [121.8028, 25.1085],
  '土城區': [121.4452, 24.9740],
  '蘆洲區': [121.4766, 25.0866],
  '林口區': [121.3889, 25.0789],
  '深坑區': [121.6145, 24.9916],
  '石碇區': [121.6603, 24.9762],
  '坪林區': [121.7148, 24.9347],
  '三芝區': [121.5031, 25.2559],
  '石門區': [121.5690, 25.2937],
  '八里區': [121.3964, 25.1564],
  '平溪區': [121.7379, 25.0213],
  '雙溪區': [121.8686, 25.0417],
  '貢寮區': [121.9035, 25.0247],
  '金山區': [121.6378, 25.2238],
  '萬里區': [121.6890, 25.1805],
  '烏來區': [121.5487, 24.8680],
  '泰山區': [121.4320, 25.0564],
  '五股區': [121.4487, 25.0780],
  '木柵區': [121.5700, 24.9989],
  // 桃園市（跨縣市服務）
  '中壢區': [121.2244, 24.9706],
  '大園區': [121.1561, 25.0378],
  '桃園區': [121.3010, 24.9937],
}
const NTPC_DISTRICTS = Object.keys(NTPC_DISTRICT_COORDS)

// 由行政區名稱推算已選的區（反查）
function districtOfCoord(lng, lat) {
  if (!lng || !lat) return ''
  for (const [d, [lo, la]] of Object.entries(NTPC_DISTRICT_COORDS)) {
    if (Math.abs(lo - lng) < 0.001 && Math.abs(la - lat) < 0.001) return d
  }
  return ''
}

// 選擇行政區時自動填座標，並同步指定服務地區
function onStartDistrictChange(d) {
  if (d && NTPC_DISTRICT_COORDS[d]) {
    const [lng, lat] = NTPC_DISTRICT_COORDS[d]
    form.start_lng = lng; form.start_lat = lat
    form.depot_lng = lng; form.depot_lat = lat
  } else {
    form.start_lng = null; form.start_lat = null
  }
  // 同步更新指定服務地區
  form.district = d || ''
}
function onEndDistrictChange(d) {
  if (d && NTPC_DISTRICT_COORDS[d]) {
    const [lng, lat] = NTPC_DISTRICT_COORDS[d]
    form.end_lng = lng; form.end_lat = lat
  } else {
    form.end_lng = null; form.end_lat = null
  }
}

const PAGE_SIZE_V = 30
const vPage = ref(1)
const pagedVehicles = computed(() => store.items.slice((vPage.value - 1) * PAGE_SIZE_V, vPage.value * PAGE_SIZE_V))
watch(() => store.items, () => { vPage.value = 1 })

const showForm = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const form = reactive(blank())
const startDistrict = ref('')
const endDistrict = ref('')

onMounted(() => store.fetchAll())

function openCreate() {
  Object.assign(form, blank())
  startDistrict.value = ''
  endDistrict.value = ''
  editingId.value = null
  showForm.value = true
}
function openEdit(v) {
  Object.assign(form, {
    ...v,
    shift_start: v.shift_start?.slice(0, 5) || '',
    shift_end: v.shift_end?.slice(0, 5) || '',
  })
  // 反查座標對應行政區
  startDistrict.value = districtOfCoord(v.start_lng, v.start_lat)
  endDistrict.value   = districtOfCoord(v.end_lng,   v.end_lat)
  editingId.value = v.id
  showForm.value = true
  nextTick(() => formRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
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
  <div v-if="showForm" ref="formRef" class="card shadow-sm mb-3">
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
        <div class="col-12"><hr class="my-1" />
          <span class="small text-muted">🚩 出車起點 / 收車終點：選擇行政區後自動填入區公所座標，作為派遣路線首末錨點。</span>
        </div>
        <div class="col-6 col-md-4">
          <label class="form-label">出車起點（行政區）</label>
          <select v-model="startDistrict" class="form-select" @change="onStartDistrictChange(startDistrict)">
            <option value="">— 未設定 —</option>
            <option v-for="d in NTPC_DISTRICTS" :key="d" :value="d">{{ d }}</option>
          </select>
          <div v-if="startDistrict && NTPC_DISTRICT_COORDS[startDistrict]" class="text-muted small mt-1">
            座標：{{ NTPC_DISTRICT_COORDS[startDistrict][0].toFixed(4) }}, {{ NTPC_DISTRICT_COORDS[startDistrict][1].toFixed(4) }}
          </div>
        </div>
        <div class="col-6 col-md-4">
          <label class="form-label">收車終點（行政區）</label>
          <select v-model="endDistrict" class="form-select" @change="onEndDistrictChange(endDistrict)">
            <option value="">— 同出車起點 —</option>
            <option v-for="d in NTPC_DISTRICTS" :key="d" :value="d">{{ d }}</option>
          </select>
          <div v-if="endDistrict && NTPC_DISTRICT_COORDS[endDistrict]" class="text-muted small mt-1">
            座標：{{ NTPC_DISTRICT_COORDS[endDistrict][0].toFixed(4) }}, {{ NTPC_DISTRICT_COORDS[endDistrict][1].toFixed(4) }}
          </div>
        </div>
        <div class="col-md-4">
          <label class="form-label">指定服務地區</label>
          <select v-model="form.district" class="form-select">
            <option value="">不限地區</option>
            <option v-for="d in NTPC_DISTRICTS" :key="d" :value="d">{{ d }}</option>
          </select>
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
          <th>#</th><th>車牌</th><th>車種</th><th>座位/輪椅</th><th>起訖點</th><th>班別</th><th>服務地區</th><th>狀態</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in pagedVehicles" :key="v.id">
          <td>{{ v.id }}</td>
          <td>{{ v.plate || '-' }}</td>
          <td>
            <span class="badge" :class="v.type === 'welfare' ? 'bg-warning text-dark' : 'bg-secondary'">
              {{ v.type === 'welfare' ? '福祉車' : '一般車' }}
            </span>
          </td>
          <td>{{ v.seats }} 座<span v-if="v.wheelchair" class="text-info"> · ♿{{ v.wheelchair }}</span></td>
          <td>
            <template v-if="v.start_lng != null">
              <span class="badge bg-info text-dark me-1">{{ districtOfCoord(v.start_lng, v.start_lat) || '已設' }}</span>
              <span v-if="v.end_lng != null && districtOfCoord(v.end_lng, v.end_lat) !== districtOfCoord(v.start_lng, v.start_lat)"
                    class="badge bg-secondary">→{{ districtOfCoord(v.end_lng, v.end_lat) }}</span>
            </template>
            <span v-else class="text-muted">—</span>
          </td>
          <td>{{ (v.shift_start || '').slice(0,5) }} ~ {{ (v.shift_end || '').slice(0,5) }}</td>
          <td>
            <span v-if="v.district" class="badge bg-primary">{{ v.district }}</span>
            <span v-else class="text-muted small">不限</span>
          </td>
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
          <td colspan="9" class="text-center text-muted py-4">尚無車輛,點右上角新增。</td>
        </tr>
      </tbody>
    </table>
    <Pagination :total="store.items.length" v-model:page="vPage" :page-size="PAGE_SIZE_V" />
  </div>
</template>
