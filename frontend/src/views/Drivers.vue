<script setup>
import { onMounted, ref, reactive } from 'vue'
import { useDriversStore } from '../stores/drivers'
import { useVehiclesStore } from '../stores/vehicles'
import client from '../api/client'

const store = useDriversStore()
const vehicles = useVehiclesStore()

const blank = () => ({
  name: '',
  phone: '',
  license_no: '',
  vehicle_id: null,
  active: true,
})

const showForm = ref(false)
const editingId = ref(null)
const form = reactive(blank())

onMounted(() => {
  store.fetchAll()
  vehicles.fetchAll()
})

function openCreate() {
  Object.assign(form, blank())
  editingId.value = null
  showForm.value = true
}
function openEdit(d) {
  Object.assign(form, { ...d })
  editingId.value = d.id
  showForm.value = true
}
async function save() {
  const payload = { ...form }
  if (editingId.value) await store.update(editingId.value, payload)
  else await store.create(payload)
  showForm.value = false
}
async function remove(d) {
  if (confirm(`確定刪除司機 ${d.name}?`)) await store.remove(d.id)
}
function vehicleLabel(id) {
  const v = vehicles.items.find((x) => x.id === id)
  return v ? (v.plate || `車輛#${v.id}`) : '未指派'
}
async function toggleSuspend(d) {
  await client.post(`/drivers/${d.id}/suspend`, null, { params: { value: !d.suspended } })
  await store.fetchAll()
}
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3">
    <span class="text-muted">共 {{ store.items.length }} 位</span>
    <button class="btn btn-primary" @click="openCreate">+ 新增司機</button>
  </div>

  <div v-if="store.error" class="alert alert-danger">{{ store.error }}</div>

  <div v-if="showForm" class="card shadow-sm mb-3">
    <div class="card-header">{{ editingId ? '編輯司機' : '新增司機' }}</div>
    <div class="card-body">
      <div class="row g-3">
        <div class="col-12 col-md-4">
          <label class="form-label">姓名 *</label>
          <input v-model="form.name" class="form-control" required />
        </div>
        <div class="col-6 col-md-4">
          <label class="form-label">電話</label>
          <input v-model="form.phone" class="form-control" />
        </div>
        <div class="col-6 col-md-4">
          <label class="form-label">駕照號碼</label>
          <input v-model="form.license_no" class="form-control" />
        </div>
        <div class="col-12 col-md-6">
          <label class="form-label">指派車輛</label>
          <select v-model="form.vehicle_id" class="form-select">
            <option :value="null">未指派</option>
            <option v-for="v in vehicles.items" :key="v.id" :value="v.id">
              {{ v.plate || `車輛#${v.id}` }}（{{ v.type === 'welfare' ? '福祉車' : '一般車' }}）
            </option>
          </select>
        </div>
        <div class="col-12 col-md-6 d-flex align-items-end">
          <div class="form-check">
            <input v-model="form.active" class="form-check-input" type="checkbox" id="dActive" />
            <label class="form-check-label" for="dActive">在職中</label>
          </div>
        </div>
      </div>
    </div>
    <div class="card-footer text-end">
      <button class="btn btn-secondary me-2" @click="showForm = false">取消</button>
      <button class="btn btn-primary" :disabled="!form.name" @click="save">儲存</button>
    </div>
  </div>

  <div class="table-responsive">
    <table class="table table-striped table-hover align-middle">
      <thead>
        <tr><th>#</th><th>姓名</th><th>電話</th><th>駕照</th><th>指派車輛</th><th>狀態</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="d in store.items" :key="d.id">
          <td>{{ d.id }}</td>
          <td>{{ d.name }}</td>
          <td>{{ d.phone || '-' }}</td>
          <td>{{ d.license_no || '-' }}</td>
          <td>{{ vehicleLabel(d.vehicle_id) }}</td>
          <td>
            <span v-if="d.suspended" class="badge bg-danger">停派</span>
            <span v-else class="badge" :class="d.active ? 'bg-success' : 'bg-secondary'">
              {{ d.active ? '在職' : '離職' }}
            </span>
          </td>
          <td class="text-nowrap">
            <button class="btn btn-sm me-1" :class="d.suspended ? 'btn-outline-success' : 'btn-outline-warning'"
                    @click="toggleSuspend(d)">{{ d.suspended ? '啟用' : '停派' }}</button>
            <button class="btn btn-sm btn-outline-primary me-1" @click="openEdit(d)">編輯</button>
            <button class="btn btn-sm btn-outline-danger" @click="remove(d)">刪除</button>
          </td>
        </tr>
        <tr v-if="!store.items.length">
          <td colspan="7" class="text-center text-muted py-4">尚無司機,點右上角新增。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
