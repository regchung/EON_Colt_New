<script setup>
import { ref, onMounted } from 'vue'
import client from '../api/client'

const today = new Date().toISOString().slice(0, 10)
const serviceDate = ref(today)
const route = ref(null)
const loading = ref(false)
const error = ref('')
const updating = ref(null)

async function fetchRoute() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await client.get('/driver/my-route', { params: { service_date: serviceDate.value } })
    route.value = data
  } catch (e) {
    error.value = e.response?.data?.detail || '載入失敗'
  } finally {
    loading.value = false
  }
}

async function updateStatus(orderId, value) {
  updating.value = orderId
  try {
    await client.post(`/driver/orders/${orderId}/status`, null, { params: { value } })
    await fetchRoute()
  } catch (e) {
    alert(e.response?.data?.detail || '更新失敗')
  } finally {
    updating.value = null
  }
}

const kindLabel = { start: '出發', pickup: '上車', delivery: '下車', end: '返回' }
const kindBadge = { start: 'secondary', pickup: 'primary', delivery: 'success', end: 'secondary' }

function nextAction(orderId, statuses) {
  const s = statuses[orderId]
  if (s === 'scheduled') return { label: '開始接送', value: 'ongoing', cls: 'warning' }
  if (s === 'ongoing') return { label: '完成', value: 'done', cls: 'success' }
  return null
}

onMounted(fetchRoute)
</script>

<template>
  <div>
    <div class="d-flex gap-2 mb-3 align-items-end flex-wrap">
      <div>
        <label class="form-label mb-1 small">服務日期</label>
        <input v-model="serviceDate" type="date" class="form-control form-control-sm" style="width:150px" />
      </div>
      <button class="btn btn-primary btn-sm" @click="fetchRoute" :disabled="loading">
        {{ loading ? '載入中…' : '查詢路單' }}
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="route">
      <div class="mb-2 text-muted small">
        車輛 #{{ route.vehicle_id }}・{{ route.service_date }}・共 {{ route.stops.length }} 站
      </div>

      <div v-if="route.stops.length === 0" class="alert alert-secondary">當日無排班路線</div>

      <div v-else class="list-group">
        <div
          v-for="stop in route.stops"
          :key="stop.id"
          class="list-group-item"
        >
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <span class="badge me-2" :class="`bg-${kindBadge[stop.kind] || 'secondary'}`">
                {{ kindLabel[stop.kind] || stop.kind }}
              </span>
              <strong class="me-2">{{ stop.eta || '--:--' }}</strong>
              <span class="text-muted">{{ stop.address || '（無地址）' }}</span>
              <span v-if="stop.order_id" class="ms-2 text-muted small">訂單 #{{ stop.order_id }}</span>
            </div>
            <div v-if="stop.order_id && nextAction(stop.order_id, route.order_statuses)">
              <button
                class="btn btn-sm"
                :class="`btn-outline-${nextAction(stop.order_id, route.order_statuses).cls}`"
                :disabled="updating === stop.order_id"
                @click="updateStatus(stop.order_id, nextAction(stop.order_id, route.order_statuses).value)"
              >
                {{ updating === stop.order_id ? '…' : nextAction(stop.order_id, route.order_statuses).label }}
              </button>
            </div>
            <div v-else-if="stop.order_id">
              <span class="badge bg-light text-dark">{{ route.order_statuses[stop.order_id] }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
