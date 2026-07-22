<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useVehiclesStore } from '../stores/vehicles'
import { useDriversStore } from '../stores/drivers'
import client from '../api/client'

const vehicles = useVehiclesStore()
const drivers  = useDriversStore()
const stats    = ref(null)
const loading  = ref(false)
const latestDate = ref('')

const today = new Date().toISOString().slice(0, 10)
const dateFrom = ref(today)
const dateTo   = ref(today)

async function loadStats() {
  loading.value = true
  try {
    const { data } = await client.get('/orders/stats', {
      params: { date_from: dateFrom.value, date_to: dateTo.value }
    })
    stats.value = data
  } catch { }
  finally { loading.value = false }
}

async function loadLatestDate() {
  try {
    const { data } = await client.get('/dispatch/board/meta')
    if (data.latest_date) {
      latestDate.value = data.latest_date
      if (dateFrom.value > data.latest_date) {
        dateFrom.value = data.latest_date
        dateTo.value   = data.latest_date
      }
    }
  } catch { }
}

onMounted(async () => {
  vehicles.fetchAll()
  drivers.fetchAll()
  await loadLatestDate()
  loadStats()
})

function setRange(days) {
  const from = new Date(latestDate.value || today)
  from.setDate(from.getDate() - days + 1)
  dateFrom.value = from.toISOString().slice(0, 10)
  dateTo.value   = latestDate.value || today
  loadStats()
}

function pct(a, b) { return b ? Math.round(a / b * 100) : 0 }
</script>

<template>
  <!-- 頁首 Banner -->
  <div class="dashboard-banner rounded-3 p-4 mb-4 d-flex align-items-center justify-content-between flex-wrap gap-3">
    <div>
      <h4 class="mb-1 fw-bold text-white">🐟 DrFish 派遣系統</h4>
      <p class="mb-0 text-white-50 small">大豐車隊 · VROOM 自動排班 · 候補管理</p>
    </div>
    <div class="text-white-50 small text-end">
      <div>最新資料：<b class="text-white">{{ latestDate || '—' }}</b></div>
      <div>車輛 {{ vehicles.items.filter(v=>v.active).length }} 台 · 司機 {{ drivers.items.length }} 位</div>
    </div>
  </div>

  <!-- 查詢列 -->
  <div class="card shadow-sm mb-4 border-0">
    <div class="card-body py-2 d-flex flex-wrap align-items-center gap-2">
      <span class="text-muted small">📅</span>
      <input v-model="dateFrom" type="date" class="form-control form-control-sm" style="width:145px" />
      <span class="text-muted">～</span>
      <input v-model="dateTo" type="date" class="form-control form-control-sm" style="width:145px" />
      <button class="btn btn-sm btn-primary px-3" :disabled="loading" @click="loadStats">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>查詢
      </button>
      <div class="btn-group btn-group-sm">
        <button class="btn btn-outline-secondary" @click="setRange(1)">今日</button>
        <button class="btn btn-outline-secondary" @click="setRange(7)">近7日</button>
        <button class="btn btn-outline-secondary" @click="setRange(30)">近30日</button>
      </div>
      <span v-if="stats" class="ms-auto text-muted small">
        {{ stats.date_from === stats.date_to ? stats.date_from : stats.date_from + ' ～ ' + stats.date_to }}
      </span>
    </div>
  </div>

  <template v-if="stats">
    <!-- 第一列：派遣狀況 -->
    <div class="row g-3 mb-3">
      <!-- 訂單總數 -->
      <div class="col-12 col-sm-6 col-xl-3">
        <RouterLink to="/orders" class="text-decoration-none">
          <div class="stat-card h-100" style="--accent:#4472C4">
            <div class="stat-icon">📋</div>
            <div class="stat-value text-primary">{{ stats.total.toLocaleString() }}</div>
            <div class="stat-label">訂單總數</div>
            <div class="stat-bar mt-2">
              <div class="progress" style="height:4px">
                <div class="progress-bar bg-primary" :style="{ width: stats.dispatch_rate + '%' }"></div>
              </div>
              <div class="d-flex justify-content-between mt-1" style="font-size:.7rem">
                <span class="text-muted">派遣率</span>
                <span class="fw-bold text-primary">{{ stats.dispatch_rate }}%</span>
              </div>
            </div>
          </div>
        </RouterLink>
      </div>

      <!-- 已派遣 -->
      <div class="col-12 col-sm-6 col-xl-3">
        <div class="stat-card h-100" style="--accent:#198754">
          <div class="stat-icon">✅</div>
          <div class="stat-value text-success">{{ stats.dispatched.toLocaleString() }}</div>
          <div class="stat-label">已派遣</div>
          <div class="mt-2 d-flex gap-2" style="font-size:.72rem">
            <span class="badge bg-success bg-opacity-10 text-success border border-success border-opacity-25">一般 {{ stats.normal.toLocaleString() }}</span>
            <span class="badge bg-warning bg-opacity-10 text-warning border border-warning border-opacity-25">候補 {{ stats.standby_success.toLocaleString() }}</span>
          </div>
        </div>
      </div>

      <!-- 尚未派遣 -->
      <div class="col-12 col-sm-6 col-xl-3">
        <RouterLink to="/orders" class="text-decoration-none">
          <div class="stat-card h-100" style="--accent:#fd7e14">
            <div class="stat-icon">⏳</div>
            <div class="stat-value text-warning">{{ stats.unassigned.toLocaleString() }}</div>
            <div class="stat-label">尚未派遣</div>
            <div class="mt-2" style="font-size:.72rem;color:#fd7e14">
              佔總訂單 {{ pct(stats.unassigned, stats.total) }}%
            </div>
          </div>
        </RouterLink>
      </div>

      <!-- 取消 / 其他 -->
      <div class="col-12 col-sm-6 col-xl-3">
        <div class="stat-card h-100" style="--accent:#6c757d">
          <div class="stat-icon">🚫</div>
          <div class="stat-value text-secondary">{{ stats.other.toLocaleString() }}</div>
          <div class="stat-label">取消 / 其他</div>
          <div class="mt-2" style="font-size:.72rem;color:#6c757d">
            佔總訂單 {{ pct(stats.other, stats.total) }}%
          </div>
        </div>
      </div>
    </div>

    <!-- 第二列：候補分析 -->
    <div class="card shadow-sm border-0 mb-3">
      <div class="card-header bg-white border-bottom py-2 d-flex align-items-center gap-2">
        <span class="fw-semibold">🕐 候補分析</span>
        <span class="text-muted small ms-1">共 {{ stats.standby_total.toLocaleString() }} 筆候補訂單</span>
      </div>
      <div class="card-body">
        <div class="row g-3 align-items-center">
          <div class="col-12 col-md-4">
            <!-- 大數字顯示成功率 -->
            <div class="text-center py-2">
              <div style="font-size:3.5rem;font-weight:700;line-height:1"
                   :class="stats.standby_rate>=90?'text-success':stats.standby_rate>=70?'text-warning':'text-danger'">
                {{ stats.standby_rate }}%
              </div>
              <div class="text-muted mt-1">候補成功率</div>
            </div>
          </div>
          <div class="col-12 col-md-8">
            <div class="mb-3">
              <div class="d-flex justify-content-between small mb-1">
                <span class="text-success fw-semibold">✅ 候補成功</span>
                <span class="fw-bold">{{ stats.standby_success.toLocaleString() }} 筆</span>
              </div>
              <div class="progress" style="height:10px;border-radius:8px">
                <div class="progress-bar bg-success" style="border-radius:8px"
                     :style="{ width: pct(stats.standby_success, stats.standby_total) + '%' }"></div>
              </div>
            </div>
            <div>
              <div class="d-flex justify-content-between small mb-1">
                <span class="text-danger fw-semibold">❌ 候補未成功</span>
                <span class="fw-bold">{{ (stats.standby_total - stats.standby_success).toLocaleString() }} 筆</span>
              </div>
              <div class="progress" style="height:10px;border-radius:8px">
                <div class="progress-bar bg-danger" style="border-radius:8px"
                     :style="{ width: pct(stats.standby_total - stats.standby_success, stats.standby_total) + '%' }"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </template>

  <!-- 車隊快速連結 -->
  <div class="row g-3">
    <div class="col-6 col-md-3">
      <RouterLink to="/dispatch-board" class="text-decoration-none">
        <div class="quick-link">🧲<div>派遣看板</div></div>
      </RouterLink>
    </div>
    <div class="col-6 col-md-3">
      <RouterLink to="/daily-tasks" class="text-decoration-none">
        <div class="quick-link">🪪<div>任務口卡</div></div>
      </RouterLink>
    </div>
    <div class="col-6 col-md-3">
      <RouterLink to="/orders" class="text-decoration-none">
        <div class="quick-link">📋<div>訂單管理</div></div>
      </RouterLink>
    </div>
    <div class="col-6 col-md-3">
      <RouterLink to="/reports" class="text-decoration-none">
        <div class="quick-link">📈<div>報表</div></div>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
/* Banner */
.dashboard-banner {
  background: linear-gradient(135deg, #1a237e 0%, #1565C0 60%, #0288D1 100%);
  border: none;
}

/* 統計卡 */
.stat-card {
  background: #fff;
  border: 1px solid #e9ecef;
  border-radius: 12px;
  padding: 1.25rem;
  position: relative;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0,0,0,.06);
  transition: box-shadow .2s, transform .2s;
}
.stat-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.12); transform: translateY(-2px); }
.stat-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  background: var(--accent, #4472C4);
  border-radius: 12px 12px 0 0;
}
.stat-icon { font-size: 1.4rem; margin-bottom: .4rem; }
.stat-value { font-size: 2.2rem; font-weight: 700; line-height: 1.1; }
.stat-label { color: #6c757d; font-size: .82rem; margin-top: .2rem; }

/* 快速連結 */
.quick-link {
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 12px;
  padding: 1.1rem;
  text-align: center;
  font-size: 1.5rem;
  color: #495057;
  transition: all .2s;
  cursor: pointer;
}
.quick-link div { font-size: .78rem; margin-top: .3rem; color: #6c757d; }
.quick-link:hover { background: #e8f0fe; border-color: #4472C4; color: #4472C4; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(68,114,196,.15); }
.quick-link:hover div { color: #4472C4; }
</style>
