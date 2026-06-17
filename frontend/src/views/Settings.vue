<script setup>
import { computed, onMounted, ref } from 'vue'
import client from '../api/client'

const items = ref([])
const loading = ref(false)
const error = ref('')
const toast = ref('')
const savingKey = ref('')

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
  } catch (e) {
    error.value = e.response?.data?.detail || '讀取失敗(需管理員權限)'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function flash(msg) { toast.value = msg; setTimeout(() => { toast.value = '' }, 3000) }

async function save(it) {
  savingKey.value = it.key
  try {
    await client.put(`/settings/${encodeURIComponent(it.key)}`, {
      value: String(it.value), value_type: it.value_type,
      group: it.group, label: it.label, description: it.description,
    })
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
          <tr v-for="it in rows" :key="it.key">
            <td><div class="fw-semibold">{{ it.label || it.key }}</div><code class="small text-muted">{{ it.key }}</code></td>
            <td>
              <select v-if="it.value_type === 'bool'" v-model="it.value" class="form-select form-select-sm">
                <option value="true">是</option><option value="false">否</option>
              </select>
              <input v-else v-model="it.value" :type="it.value_type === 'str' ? 'text' : 'number'" class="form-control form-control-sm" />
            </td>
            <td><span class="badge bg-light text-dark">{{ it.value_type }}</span></td>
            <td class="small text-muted">{{ it.description }}</td>
            <td class="text-nowrap">
              <button class="btn btn-sm btn-outline-primary me-1" :disabled="savingKey === it.key" @click="save(it)">
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
