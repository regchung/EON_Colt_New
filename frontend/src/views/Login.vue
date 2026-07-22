<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e?.response?.data?.detail || '登入失敗'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="d-flex align-items-center justify-content-center" style="min-height: 100vh; background: #f1f3f5;">
    <div class="card shadow-sm" style="width: 360px; max-width: 92vw;">
      <div class="card-body p-4">
        <h4 class="text-center mb-1">🚖 DrFish</h4>
        <p class="text-center text-muted small mb-4">車隊派遣系統登入</p>
        <form @submit.prevent="submit">
          <div class="mb-3">
            <label class="form-label">帳號</label>
            <input v-model="username" class="form-control" autocomplete="username" required />
          </div>
          <div class="mb-3">
            <label class="form-label">密碼</label>
            <input v-model="password" type="password" class="form-control" autocomplete="current-password" required />
          </div>
          <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
          <button class="btn btn-primary w-100" :disabled="loading">
            {{ loading ? '登入中…' : '登入' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
