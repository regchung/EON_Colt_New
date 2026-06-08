<script setup>
import { onMounted, ref, reactive } from 'vue'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const users = ref([])
const error = ref('')
const form = reactive({ username: '', password: '' })

async function load() {
  const { data } = await client.get('/users')
  users.value = data
}
onMounted(load)

async function addUser() {
  error.value = ''
  try {
    await client.post('/users', { username: form.username, password: form.password })
    form.username = ''
    form.password = ''
    await load()
  } catch (e) {
    error.value = e?.response?.data?.detail || '新增失敗'
  }
}
async function resetPwd(u) {
  const pw = prompt(`為「${u.username}」設定新密碼(至少 4 碼):`)
  if (!pw) return
  try {
    await client.put(`/users/${u.id}/password`, { password: pw })
    alert('密碼已更新')
  } catch (e) {
    alert(e?.response?.data?.detail || '更新失敗')
  }
}
async function removeUser(u) {
  if (!confirm(`確定刪除使用者「${u.username}」?`)) return
  try {
    await client.delete(`/users/${u.id}`)
    await load()
  } catch (e) {
    alert(e?.response?.data?.detail || '刪除失敗')
  }
}
</script>

<template>
  <div class="card shadow-sm mb-3" style="max-width: 520px">
    <div class="card-header">新增使用者</div>
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div class="col-12 col-sm-5">
          <label class="form-label">帳號</label>
          <input v-model="form.username" class="form-control" />
        </div>
        <div class="col-12 col-sm-5">
          <label class="form-label">密碼(≥4 碼)</label>
          <input v-model="form.password" type="password" class="form-control" />
        </div>
        <div class="col-12 col-sm-2">
          <button class="btn btn-primary w-100" :disabled="!form.username || form.password.length < 4" @click="addUser">新增</button>
        </div>
      </div>
      <div v-if="error" class="alert alert-danger mt-2 py-2 mb-0">{{ error }}</div>
    </div>
  </div>

  <div class="table-responsive">
    <table class="table table-striped align-middle">
      <thead><tr><th>#</th><th>帳號</th><th>建立時間</th><th></th></tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.id }}</td>
          <td>
            {{ u.username }}
            <span v-if="u.username === auth.username" class="badge bg-info text-dark ms-1">目前登入</span>
          </td>
          <td class="small text-muted">{{ (u.created_at || '').slice(0, 16).replace('T', ' ') }}</td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-outline-primary me-1" @click="resetPwd(u)">改密碼</button>
            <button class="btn btn-sm btn-outline-danger" @click="removeUser(u)">刪除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
