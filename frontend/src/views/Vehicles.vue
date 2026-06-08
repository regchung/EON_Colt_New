<script setup>
import { onMounted, ref, reactive } from 'vue'
import { useVehiclesStore } from '../stores/vehicles'

const store = useVehiclesStore()

const blank = () => ({
  plate: '',
  type: 'normal',
  seats: 4,
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
    <button class="btn btn-primary" @click="openCreate">+ 新增車輛</button>
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
        <div class="col-6 col-md-4">
          <label class="form-label">座位數</label>
          <input v-model.number="form.seats" type="number" min="1" class="form-control" />
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
          <th>#</th><th>車牌</th><th>車種</th><th>座位</th><th>班別</th><th>狀態</th><th></th>
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
          <td>{{ v.seats }}</td>
          <td>{{ (v.shift_start || '').slice(0,5) }} ~ {{ (v.shift_end || '').slice(0,5) }}</td>
          <td>
            <span class="badge" :class="v.active ? 'bg-success' : 'bg-secondary'">
              {{ v.active ? '啟用' : '停用' }}
            </span>
          </td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-outline-primary me-1" @click="openEdit(v)">編輯</button>
            <button class="btn btn-sm btn-outline-danger" @click="remove(v)">刪除</button>
          </td>
        </tr>
        <tr v-if="!store.items.length">
          <td colspan="7" class="text-center text-muted py-4">尚無車輛,點右上角新增。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
