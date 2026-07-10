<script setup>
import { onMounted, ref, reactive } from 'vue'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const users = ref([])
const error = ref('')
const form = reactive({ username: '', password: '', role: 'dispatcher' })

const ROLES = [
  { value: 'admin',      label: '系統管理者', badge: 'danger',  desc: '完整權限：使用者管理、參數設定、派遣分析、操作所有功能' },
  { value: 'dispatcher', label: '調度員',    badge: 'primary', desc: '日常操作：訂單、排班、看板、名冊、基礎資料；不含分析區' },
  { value: 'driver',     label: '司機',      badge: 'success', desc: '僅限「我的路單」：查看當日自己負責的行程' },
]

function roleInfo(r) { return ROLES.find(x => x.value === r) || { label: r, badge: 'secondary', desc: '' } }

async function load() {
  const { data } = await client.get('/users')
  users.value = data
}
onMounted(load)

async function addUser() {
  error.value = ''
  try {
    await client.post('/users', { username: form.username, password: form.password, role: form.role })
    form.username = ''
    form.password = ''
    form.role = 'dispatcher'
    await load()
  } catch (e) {
    error.value = e?.response?.data?.detail || '新增失敗'
  }
}

async function changeRole(u) {
  const ri = roleInfo(u.role)
  const opts = ROLES.map((r, i) => `${i + 1}. ${r.label}（${r.value}）`).join('\n')
  const ans = prompt(`修改「${u.username}」的角色\n目前：${ri.label}\n\n${opts}\n\n請輸入角色代碼（admin / dispatcher / driver）：`)
  if (!ans || !['admin', 'dispatcher', 'driver'].includes(ans.trim())) return
  try {
    await client.put(`/users/${u.id}/role`, { role: ans.trim() })
    await load()
  } catch (e) { alert(e?.response?.data?.detail || '更新失敗') }
}

async function resetPwd(u) {
  const pw = prompt(`為「${u.username}」設定新密碼（至少 4 碼）：`)
  if (!pw) return
  try {
    await client.put(`/users/${u.id}/password`, { password: pw })
    alert('密碼已更新')
  } catch (e) { alert(e?.response?.data?.detail || '更新失敗') }
}

async function removeUser(u) {
  if (!confirm(`確定刪除使用者「${u.username}」？`)) return
  try {
    await client.delete(`/users/${u.id}`)
    await load()
  } catch (e) { alert(e?.response?.data?.detail || '刪除失敗') }
}
</script>

<template>
  <!-- 角色說明 -->
  <div class="card shadow-sm mb-3">
    <div class="card-header fw-bold">角色權限說明</div>
    <div class="card-body pb-2">
      <div v-for="r in ROLES" :key="r.value" class="d-flex align-items-start gap-2 mb-2">
        <span :class="`badge bg-${r.badge} mt-1`" style="min-width:72px;text-align:center">{{ r.label }}</span>
        <span class="small text-muted">{{ r.desc }}</span>
      </div>
    </div>
  </div>

  <!-- 新增使用者 -->
  <div class="card shadow-sm mb-3" style="max-width:620px">
    <div class="card-header fw-bold">新增使用者</div>
    <div class="card-body">
      <div class="row g-2 align-items-end">
        <div class="col-12 col-sm-4">
          <label class="form-label small mb-1">帳號</label>
          <input v-model="form.username" class="form-control form-control-sm" placeholder="登入帳號" />
        </div>
        <div class="col-12 col-sm-4">
          <label class="form-label small mb-1">密碼（≥4 碼）</label>
          <input v-model="form.password" type="password" class="form-control form-control-sm" />
        </div>
        <div class="col-12 col-sm-3">
          <label class="form-label small mb-1">角色</label>
          <select v-model="form.role" class="form-select form-select-sm">
            <option v-for="r in ROLES" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </div>
        <div class="col-12 col-sm-1">
          <button class="btn btn-primary btn-sm w-100"
                  :disabled="!form.username || form.password.length < 4"
                  @click="addUser">新增</button>
        </div>
      </div>
      <div v-if="error" class="alert alert-danger mt-2 py-2 mb-0 small">{{ error }}</div>
    </div>
  </div>

  <!-- 使用者清單 -->
  <div class="table-responsive">
    <table class="table table-striped align-middle">
      <thead class="table-dark">
        <tr>
          <th>#</th>
          <th>帳號</th>
          <th>角色</th>
          <th>建立時間</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td class="text-muted small">{{ u.id }}</td>
          <td>
            {{ u.username }}
            <span v-if="u.username === auth.username" class="badge bg-info text-dark ms-1">目前登入</span>
          </td>
          <td>
            <span :class="`badge bg-${roleInfo(u.role).badge}`">{{ roleInfo(u.role).label }}</span>
          </td>
          <td class="small text-muted">{{ (u.created_at || '').slice(0, 16).replace('T', ' ') }}</td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-outline-secondary me-1" @click="changeRole(u)" title="變更角色">角色</button>
            <button class="btn btn-sm btn-outline-primary me-1" @click="resetPwd(u)" title="重設密碼">密碼</button>
            <button class="btn btn-sm btn-outline-danger" @click="removeUser(u)"
                    :disabled="u.username === auth.username" title="刪除">刪除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
