<script setup>
import { computed, onMounted, ref } from 'vue'
import client from '../api/client'

const items = ref([])
const loading = ref(false)
const error = ref('')
const toast = ref('')
const savingKey = ref('')
const original = ref({})   // key → 已儲存的值(判斷是否未儲存)

function isDirty(it) { return String(it.value) !== original.value[it.key] }

const blankNew = () => ({ key: '', value: '', value_type: 'str', group: '', label: '', description: '' })
const showNew = ref(false)
const newItem = ref(blankNew())

const groups = computed(() => {
  const g = {}
  for (const it of items.value) (g[it.group || '其他'] ||= []).push(it)
  return g
})

async function load() {
  loading.value = true; error.value = ''
  try {
    const { data } = await client.get('/settings')
    items.value = data
    original.value = Object.fromEntries(data.map((x) => [x.key, String(x.value)]))
  } catch (e) {
    error.value = e.response?.data?.detail || '讀取失敗(需管理員權限)'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function flash(msg) { toast.value = msg; setTimeout(() => { toast.value = '' }, 3000) }

// --- 每趟工時 歷史校準 ---
const cal = ref(null)
const calLoading = ref(false)
const calApplying = ref(false)
async function loadCal() {
  try { const { data } = await client.get('/dispatch/calibration'); cal.value = data } catch { /* 略過 */ }
}
async function applyCal() {
  if (!confirm('重新從歷史校準每趟作業時間?會覆寫各車行校準值,並即時影響自動派遣與逐車對比。')) return
  calApplying.value = true
  try {
    await client.post('/dispatch/calibration/apply')
    await loadCal()
    flash('已從歷史重新校準每趟工時')
  } catch (e) {
    error.value = e.response?.data?.detail || '校準失敗'
  } finally { calApplying.value = false }
}
onMounted(loadCal)

async function save(it) {
  savingKey.value = it.key
  try {
    await client.put(`/settings/${encodeURIComponent(it.key)}`, {
      value: String(it.value), value_type: it.value_type,
      group: it.group, label: it.label, description: it.description,
    })
    original.value[it.key] = String(it.value)   // 更新已儲存基準 → 清除未儲存標示
    flash(`已儲存「${it.label || it.key}」`)
  } catch (e) {
    error.value = e.response?.data?.detail || '儲存失敗'
  } finally {
    savingKey.value = ''
  }
}

async function createItem() {
  if (!newItem.value.key) { error.value = '請填 key'; return }
  try {
    await client.post('/settings', newItem.value)
    showNew.value = false; newItem.value = blankNew()
    await load(); flash('已新增參數')
  } catch (e) {
    error.value = e.response?.data?.detail || '新增失敗'
  }
}

async function removeItem(it) {
  if (!confirm(`刪除參數「${it.key}」?`)) return
  try {
    await client.delete(`/settings/${encodeURIComponent(it.key)}`)
    await load(); flash('已刪除')
  } catch (e) {
    error.value = e.response?.data?.detail || '刪除失敗'
  }
}
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3">
    <span class="text-muted">系統參數設定(僅系統管理者)。即時派遣會即時採用這些參數;回測沿用固定方法學。</span>
    <button class="btn btn-primary" @click="showNew = !showNew">+ 新增參數</button>
  </div>

  <div v-if="error" class="alert alert-danger">{{ error }}</div>
  <div v-if="toast" class="alert alert-success py-2">{{ toast }}</div>

  <!-- 每趟工時:歷史校準(依車行×福祉/一般)-->
  <div v-if="cal" class="card shadow-sm mb-3 border-info">
    <div class="card-header py-2 d-flex justify-content-between align-items-center">
      <span class="fw-semibold">🧪 每趟作業時間 — 歷史校準(依車行/福祉)</span>
      <button class="btn btn-sm btn-outline-info" :disabled="calApplying" @click="applyCal">
        <span v-if="calApplying" class="spinner-border spinner-border-sm me-1"></span>從歷史重新校準
      </button>
    </div>
    <div class="card-body py-2">
      <p class="small text-muted mb-2">
        從歷史「背靠背連續趟」反推每趟真實上下車作業時間(已扣車程與調度空車),取代全域固定 40 分。
        會隨距離變的車程由 OSRM 動態處理;區域(山區/都會)差異由「分車行各自校準」自動吸收;樣本不足者退回全域。
        <span class="text-info">套用後即時影響自動派遣與逐車對比。</span>
      </p>
      <div class="table-responsive">
        <table class="table table-sm table-bordered align-middle mb-1">
          <thead class="table-light"><tr>
            <th>車行</th><th>一般單/趟(分)</th><th>福祉單/趟(分)</th><th>速度係數</th><th>樣本(趟對)</th>
          </tr></thead>
          <tbody>
            <tr v-for="a in cal.applied" :key="a.fleet">
              <td>{{ a.fleet === '*' ? '＊全域預設' : a.fleet }}</td>
              <td>{{ a.service_normal_min }}</td>
              <td>{{ a.service_welfare_min }}</td>
              <td :class="{ 'text-warning': Math.abs(a.speed_factor - 1) > 0.05 }">{{ a.speed_factor }}</td>
              <td class="text-muted">{{ a.samples.toLocaleString() }}</td>
            </tr>
            <tr v-if="!cal.applied.length"><td colspan="5" class="text-center text-muted">尚未校準,點右上角「從歷史重新校準」</td></tr>
          </tbody>
        </table>
      </div>
      <div class="small text-muted">
        全域實證:一般 {{ cal.recommendation.global.normal_min }} 分、福祉 {{ cal.recommendation.global.welfare_min }} 分;
        隱含車速 {{ cal.recommendation.global.speed_kmh }} km/h(樣本 {{ cal.recommendation.global.normal_samples + cal.recommendation.global.welfare_samples }} 趟對)。
      </div>
    </div>
  </div>

  <!-- 新增 -->
  <div v-if="showNew" class="card shadow-sm mb-3"><div class="card-body">
    <div class="row g-2">
      <div class="col-6 col-md-3"><label class="form-label">key</label>
        <input v-model="newItem.key" class="form-control" placeholder="例:max_work_hours" /></div>
      <div class="col-6 col-md-3"><label class="form-label">值</label>
        <input v-model="newItem.value" class="form-control" /></div>
      <div class="col-6 col-md-2"><label class="form-label">型別</label>
        <select v-model="newItem.value_type" class="form-select">
          <option>str</option><option>int</option><option>float</option><option>bool</option>
        </select></div>
      <div class="col-6 col-md-2"><label class="form-label">分組</label>
        <input v-model="newItem.group" class="form-control" /></div>
      <div class="col-12 col-md-2"><label class="form-label">顯示名稱</label>
        <input v-model="newItem.label" class="form-control" /></div>
    </div>
    <div class="text-end mt-2">
      <button class="btn btn-secondary btn-sm me-2" @click="showNew = false">取消</button>
      <button class="btn btn-primary btn-sm" @click="createItem">建立</button>
    </div>
  </div></div>

  <div v-if="loading" class="text-muted">載入中…</div>

  <div v-for="(rows, gname) in groups" :key="gname" class="card shadow-sm mb-3">
    <div class="card-header py-2 fw-semibold">{{ gname }}</div>
    <div class="table-responsive">
      <table class="table table-sm align-middle mb-0">
        <thead><tr><th>參數</th><th style="width:160px">值</th><th style="width:90px">型別</th><th>說明</th><th style="width:130px"></th></tr></thead>
        <tbody>
          <tr v-for="it in rows" :key="it.key" :class="{ 'table-warning': isDirty(it) }">
            <td><div class="fw-semibold">{{ it.label || it.key }}</div><code class="small text-muted">{{ it.key }}</code></td>
            <td>
              <select v-if="it.value_type === 'bool'" v-model="it.value" class="form-select form-select-sm">
                <option value="true">是</option><option value="false">否</option>
              </select>
              <input v-else v-model="it.value" :type="it.value_type === 'str' ? 'text' : 'number'"
                     class="form-control form-control-sm" :class="{ 'border-warning': isDirty(it) }" />
              <span v-if="isDirty(it)" class="badge bg-warning text-dark mt-1">● 未儲存,請按右側「儲存」</span>
            </td>
            <td><span class="badge bg-light text-dark">{{ it.value_type }}</span></td>
            <td class="small text-muted">{{ it.description }}</td>
            <td class="text-nowrap">
              <button class="btn btn-sm me-1" :class="isDirty(it) ? 'btn-warning' : 'btn-outline-primary'"
                      :disabled="savingKey === it.key" @click="save(it)">
                <span v-if="savingKey === it.key" class="spinner-border spinner-border-sm"></span>
                <span v-else>儲存</span>
              </button>
              <button class="btn btn-sm btn-outline-danger" @click="removeItem(it)">刪</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
