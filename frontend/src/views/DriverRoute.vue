<script setup>
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { getPushState, enablePush, disablePush, sendTestPush } from '../composables/usePush'

const today = new Date().toISOString().slice(0, 10)
const serviceDate = ref(today)
const route = ref(null)
const loading = ref(false)
const error = ref('')
const updating = ref(null)

// --- Web Push 通知 ---
const push = ref({ supported: false, subscribed: false, permission: 'default' })
const pushBusy = ref(false)
const pushMsg = ref('')

async function refreshPush() {
  push.value = await getPushState()
}
function flashPush(m) { pushMsg.value = m; setTimeout(() => { pushMsg.value = '' }, 4000) }

async function togglePush() {
  pushBusy.value = true
  try {
    if (push.value.subscribed) {
      await disablePush()
      flashPush('已關閉通知')
    } else {
      await enablePush(route.value?.driver_id ?? null)
      flashPush('已啟用通知 ✓')
    }
    await refreshPush()
  } catch (e) {
    flashPush(e.message || '操作失敗')
  } finally {
    pushBusy.value = false
  }
}

async function testPush() {
  pushBusy.value = true
  try {
    await sendTestPush(route.value?.driver_id ?? null)
    flashPush('已送出測試推播,稍候應收到通知')
  } catch (e) {
    flashPush(e.response?.data?.detail || e.message || '測試失敗')
  } finally {
    pushBusy.value = false
  }
}

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

onMounted(async () => {
  await fetchRoute()
  await refreshPush()
})
</script>

<template>
  <div>
    <!-- 推播通知 -->
    <div class="card mb-3 border-0 bg-light">
      <div class="card-body py-2 d-flex align-items-center flex-wrap gap-2">
        <span class="me-1">🔔 派遣通知</span>
        <template v-if="!push.supported">
          <span class="badge bg-secondary">此瀏覽器/環境不支援</span>
        </template>
        <template v-else>
          <span class="badge" :class="push.subscribed ? 'bg-success' : 'bg-secondary'">
            {{ push.subscribed ? '已啟用' : '未啟用' }}
          </span>
          <button class="btn btn-sm" :class="push.subscribed ? 'btn-outline-secondary' : 'btn-primary'"
                  :disabled="pushBusy" @click="togglePush">
            {{ pushBusy ? '…' : (push.subscribed ? '關閉通知' : '啟用通知') }}
          </button>
          <button v-if="push.subscribed" class="btn btn-sm btn-outline-primary"
                  :disabled="pushBusy" @click="testPush">測試</button>
        </template>
        <span v-if="pushMsg" class="text-success small ms-1">{{ pushMsg }}</span>
      </div>
    </div>

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
