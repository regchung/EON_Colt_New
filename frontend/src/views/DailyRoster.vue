<script setup>
import { ref, computed } from 'vue'
import api from '../api/client'

const today = new Date().toISOString().slice(0, 10)
const serviceDate = ref(today)
const file = ref(null)
const fileInput = ref(null)
const loading = ref(false)
const result = ref(null)
const error = ref('')

const canUpload = computed(() => file.value && serviceDate.value)

function onFileChange(e) {
  const f = e.target.files[0]
  file.value = f || null
  error.value = ''
  result.value = null
}

function clearFile() {
  file.value = null
  error.value = ''
  result.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function upload() {
  if (!canUpload.value) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const form = new FormData()
    form.append('file', file.value)
    const { data } = await api.post(
      `/fleet/daily-roster?service_date=${serviceDate.value}`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    result.value = data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="container-fluid py-3" style="max-width:900px">
    <h5 class="mb-3">📋 每日出勤名冊上傳</h5>
    <p class="text-muted small mb-4">
      上傳當日出勤 XLS/XLSX，系統自動設定出勤車輛班別時段並將名冊外車輛設為當日停派。
    </p>

    <!-- 上傳卡 -->
    <div class="card mb-4">
      <div class="card-body">
        <div class="row g-3 align-items-end">
          <!-- 日期選擇 -->
          <div class="col-auto">
            <label class="form-label fw-semibold">服務日期</label>
            <input
              type="date"
              class="form-control"
              v-model="serviceDate"
              style="min-width:160px"
            />
          </div>

          <!-- 檔案選擇 -->
          <div class="col">
            <label class="form-label fw-semibold">出勤名冊檔案</label>
            <div class="input-group">
              <input
                ref="fileInput"
                type="file"
                class="form-control"
                accept=".xls,.xlsx"
                @change="onFileChange"
              />
              <button v-if="file" class="btn btn-outline-secondary" @click="clearFile">✕</button>
            </div>
            <div class="form-text">支援 .xls / .xlsx；需含欄位：車牌號碼、駕駛姓名、工作時段</div>
          </div>

          <!-- 上傳按鈕 -->
          <div class="col-auto">
            <button
              class="btn btn-primary"
              :disabled="!canUpload || loading"
              @click="upload"
            >
              <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
              {{ loading ? '上傳中...' : '上傳' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 錯誤 -->
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- 結果 -->
    <template v-if="result">
      <!-- 摘要卡 -->
      <div class="row g-3 mb-4">
        <div class="col-6 col-md-3">
          <div class="card text-center border-success">
            <div class="card-body py-2">
              <div class="display-6 fw-bold text-success">{{ result.on_duty }}</div>
              <small class="text-muted">當日出勤</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="card text-center border-secondary">
            <div class="card-body py-2">
              <div class="display-6 fw-bold text-secondary">{{ result.off_duty }}</div>
              <small class="text-muted">當日停派</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="card text-center">
            <div class="card-body py-2">
              <div class="display-6 fw-bold">{{ result.assignments }}</div>
              <small class="text-muted">司機車輛配對</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="card text-center">
            <div class="card-body py-2">
              <div class="display-6 fw-bold">{{ result.vehicles_updated }}</div>
              <small class="text-muted">車輛規格更新</small>
            </div>
          </div>
        </div>
      </div>

      <!-- 出勤 / 停派列表 -->
      <div class="row g-3 mb-3">
        <!-- 出勤 -->
        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header bg-success text-white py-2">
              ✅ 當日出勤車輛（{{ result.on_duty_list.length }}）
            </div>
            <div class="card-body p-0" style="max-height:320px;overflow-y:auto">
              <ul class="list-group list-group-flush">
                <li
                  v-for="plate in result.on_duty_list"
                  :key="plate"
                  class="list-group-item py-1 px-3 small"
                >{{ plate }}</li>
                <li v-if="!result.on_duty_list.length" class="list-group-item text-muted small py-1 px-3">（無）</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- 停派 -->
        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header bg-secondary text-white py-2">
              🚫 當日停派車輛（{{ result.off_duty_list.length }}）
            </div>
            <div class="card-body p-0" style="max-height:320px;overflow-y:auto">
              <ul class="list-group list-group-flush">
                <li
                  v-for="plate in result.off_duty_list"
                  :key="plate"
                  class="list-group-item py-1 px-3 small text-muted"
                >{{ plate }}</li>
                <li v-if="!result.off_duty_list.length" class="list-group-item text-muted small py-1 px-3">（無）</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- 解析錯誤 -->
      <div v-if="result.errors?.length" class="card border-warning">
        <div class="card-header text-warning py-2">⚠️ 解析警告（{{ result.errors.length }}）</div>
        <ul class="list-group list-group-flush">
          <li
            v-for="(e, i) in result.errors"
            :key="i"
            class="list-group-item small py-1 px-3"
          >第 {{ e.row }} 列：{{ e.error }}</li>
        </ul>
      </div>

      <div class="alert alert-success mt-3">
        ✅ {{ result.service_date }} 出勤名冊上傳完成。
        可至「班表」頁確認例外，或直接執行自動派遣。
      </div>
    </template>
  </div>
</template>
