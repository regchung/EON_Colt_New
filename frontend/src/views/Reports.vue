<script setup>
import { onMounted, ref, computed } from 'vue'
import client from '../api/client'

const today = new Date().toISOString().slice(0, 10)
const ago13 = new Date(Date.now() - 13 * 86400000).toISOString().slice(0, 10)
const dateFrom = ref(ago13)
const dateTo = ref(today)
const data = ref(null)
const loading = ref(false)

const STATUS_LABEL = { imported: '待排', scheduled: '已排', ongoing: '進行中', done: '完成', canceled: '取消' }

async function load() {
  loading.value = true
  try {
    const res = await client.get('/reports/overview', {
      params: { date_from: dateFrom.value, date_to: dateTo.value },
    })
    data.value = res.data
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function exportCsv() {
  const res = await client.get('/reports/export-csv', {
    params: { date_from: dateFrom.value, date_to: dateTo.value },
    responseType: 'blob',
  })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `smartcar_${dateFrom.value}_${dateTo.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const maxDay = computed(() =>
  data.value ? Math.max(1, ...data.value.by_day.map((d) => d.total)) : 1
)
function pct(n, total) {
  return total ? Math.round((n / total) * 100) : 0
}
</script>

<template>
  <div class="d-flex flex-wrap gap-2 align-items-end mb-3">
    <div><label class="form-label mb-1 small">起</label>
      <input v-model="dateFrom" type="date" class="form-control form-control-sm" style="width:160px" /></div>
    <div><label class="form-label mb-1 small">迄</label>
      <input v-model="dateTo" type="date" class="form-control form-control-sm" style="width:160px" /></div>
    <button class="btn btn-sm btn-primary" :disabled="loading" @click="load">{{ loading ? '查詢中…' : '查詢' }}</button>
    <button class="btn btn-sm btn-outline-secondary" @click="exportCsv">⬇ 匯出 CSV</button>
  </div>

  <template v-if="data">
    <!-- 統計卡 -->
    <div class="row g-3 mb-3">
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-primary">{{ data.totals.orders }}</div><small class="text-muted">訂單總數</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-success">{{ data.totals.assigned }}</div><small class="text-muted">已派遣</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-danger">{{ data.totals.unassigned }}</div><small class="text-muted">未派遣</small></div></div></div>
      <div class="col-6 col-md-3"><div class="card text-center shadow-sm"><div class="card-body py-3">
        <div class="display-6 fw-bold text-info">{{ data.totals.vehicles_active }}/{{ data.totals.vehicles_total }}</div><small class="text-muted">可用/總車輛</small></div></div></div>
    </div>

    <div class="row g-3">
      <!-- 狀態分佈 -->
      <div class="col-12 col-lg-6"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>訂單狀態分佈</h6>
        <div v-for="(cnt, st) in data.by_status" :key="st" class="mb-2">
          <div class="d-flex justify-content-between small"><span>{{ STATUS_LABEL[st] || st }}</span><span>{{ cnt }}</span></div>
          <div class="progress" style="height:8px"><div class="progress-bar" :style="{ width: pct(cnt, data.totals.orders) + '%' }"></div></div>
        </div>
      </div></div></div>

      <!-- 車種分佈 -->
      <div class="col-12 col-lg-6"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>車種需求分佈</h6>
        <div v-for="(cnt, vt) in data.by_vehicle_type" :key="vt" class="mb-2">
          <div class="d-flex justify-content-between small"><span>{{ vt === 'welfare' ? '福祉車' : '一般車' }}</span><span>{{ cnt }}</span></div>
          <div class="progress" style="height:8px">
            <div class="progress-bar" :class="vt === 'welfare' ? 'bg-warning' : 'bg-secondary'" :style="{ width: pct(cnt, data.totals.orders) + '%' }"></div>
          </div>
        </div>
      </div></div></div>

      <!-- 每日量 -->
      <div class="col-12 col-lg-7"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>每日訂單量</h6>
        <div v-for="d in data.by_day" :key="d.date" class="d-flex align-items-center mb-1">
          <span class="small text-muted" style="width:90px">{{ d.date.slice(5) }}</span>
          <div class="progress flex-grow-1" style="height:16px">
            <div class="progress-bar bg-success" :style="{ width: pct(d.assigned, maxDay) + '%' }">{{ d.assigned || '' }}</div>
            <div class="progress-bar bg-danger" :style="{ width: pct(d.unassigned, maxDay) + '%' }">{{ d.unassigned || '' }}</div>
          </div>
          <span class="small ms-2" style="width:36px">{{ d.total }}</span>
        </div>
        <small class="text-muted">🟩 已派　🟥 未派</small>
      </div></div></div>

      <!-- 每車派遣量 -->
      <div class="col-12 col-lg-5"><div class="card shadow-sm h-100"><div class="card-body">
        <h6>各車派遣量</h6>
        <table class="table table-sm mb-0">
          <tbody>
            <tr v-for="v in data.per_vehicle" :key="v.vehicle_id">
              <td>{{ v.plate }}</td><td class="text-end fw-bold">{{ v.orders }}</td>
            </tr>
            <tr v-if="!data.per_vehicle.length"><td colspan="2" class="text-muted text-center">區間內無派遣</td></tr>
          </tbody>
        </table>
      </div></div></div>
    </div>
  </template>
</template>
