<script setup>
import { computed, onMounted, ref } from 'vue'
import client from '../api/client'

const date = ref(new Date().toISOString().slice(0, 10))
const board = ref(null)
const loading = ref(false)
const error = ref('')
const dragId = ref(null)
const dragFrom = ref(null)
const fleet = ref('')        // 車行過濾
const plate = ref('')        // 車號過濾(下拉,跟隨車行)

const fleets = computed(() => {
  if (!board.value) return []
  return [...new Set(board.value.vehicles.map((v) => v.fleet).filter(Boolean))].sort()
})
const plateOptions = computed(() => {
  if (!board.value) return []
  return board.value.vehicles
    .filter((v) => !fleet.value || v.fleet === fleet.value)
    .map((v) => v.plate).filter(Boolean).sort()
})
const visibleVehicles = computed(() => {
  if (!board.value) return []
  return board.value.vehicles.filter((v) =>
    (!fleet.value || v.fleet === fleet.value)
    && (!plate.value || v.plate === plate.value))
})
function onFleetChange() {
  // 換車行時,若已選車號不在新車行內 → 清空
  if (plate.value && !plateOptions.value.includes(plate.value)) plate.value = ''
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const { data } = await client.get('/dispatch/board', { params: { service_date: date.value } })
    board.value = data
  } catch (e) { error.value = e.response?.data?.detail || '讀取失敗' } finally { loading.value = false }
}
onMounted(async () => {
  try {
    const { data } = await client.get('/dispatch/board/meta')
    if (data.latest_date) date.value = data.latest_date   // 預設跳到最近有派車的日期
  } catch (e) { /* 忽略,沿用今天 */ }
  await load()
})

function onDragStart(orderId, fromVid) { dragId.value = orderId; dragFrom.value = fromVid }
async function onDrop(toVid) {
  const id = dragId.value
  dragId.value = null
  if (id == null || toVid === dragFrom.value) return
  try {
    if (toVid === null) await client.post(`/orders/${id}/unassign`)
    else await client.post(`/orders/${id}/assign`, null, { params: { vehicle_id: toVid } })
    await load()
  } catch (e) { error.value = e.response?.data?.detail || '搬移失敗' }
}
</script>

<template>
  <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
    <span class="fw-semibold">🧲 派遣看板</span>
    <input v-model="date" type="date" class="form-control form-control-sm" style="width:160px" @change="load" />
    <button class="btn btn-sm btn-primary" :disabled="loading" @click="load">{{ loading ? '讀取中…' : '重新整理' }}</button>
    <select v-model="fleet" class="form-select form-select-sm" style="width:140px" title="車行過濾"
            @change="onFleetChange">
      <option value="">全部車行</option>
      <option v-for="f in fleets" :key="f" :value="f">{{ f }}</option>
    </select>
    <select v-model="plate" class="form-select form-select-sm" style="width:130px" title="車號過濾">
      <option value="">全部車號</option>
      <option v-for="p in plateOptions" :key="p" :value="p">{{ p }}</option>
    </select>
    <span v-if="board" class="small text-muted">
      顯示 {{ visibleVehicles.length }}/{{ board.vehicles.length }} 車 · 未指派 {{ board.unassigned_count }}
    </span>
    <span class="small text-muted ms-auto">拖曳訂單卡到其他車欄即重新指派;拖回「未指派」可卸載。紅框=時間衝突。</span>
  </div>
  <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>

  <!-- 該日無派車資料 -->
  <div v-if="board && !board.vehicles.length && !board.unassigned.length" class="alert alert-info py-2">
    該日期（<b>{{ date }}</b>)無排班/派遣車輛。請改選有資料的日期(例:已排班日或歷史日),
    或先到「訂單管理」按「🚀 一鍵排班」。
  </div>
  <!-- 有資料但過濾後無車 -->
  <div v-else-if="board && board.vehicles.length && !visibleVehicles.length" class="alert alert-warning py-2">
    車行/車牌過濾後沒有符合的車輛(全部 {{ board.vehicles.length }} 車)。請放寬過濾條件。
  </div>

  <div v-if="board" class="board-scroll d-flex gap-2 pb-2" style="overflow-x:auto">
    <!-- 未指派欄(固定左側,只有右側車欄左右滑動) -->
    <div class="board-col unassigned-col border rounded bg-light" @dragover.prevent @drop="onDrop(null)">
      <div class="board-head bg-secondary text-white px-2 py-1 small fw-semibold">
        未指派 <span class="badge bg-light text-dark">{{ board.unassigned.length }}</span>
      </div>
      <div class="board-body p-1">
        <div v-for="t in board.unassigned" :key="t.order_id" class="trip-card border rounded p-1 mb-1 bg-white"
             draggable="true" @dragstart="onDragStart(t.order_id, null)">
          <div class="d-flex justify-content-between"><b>{{ t.time }}</b>
            <span v-if="t.welfare" class="badge bg-warning text-dark">福</span></div>
          <div class="small">{{ t.passenger || '—' }}</div>
          <div class="text-muted" style="font-size:.72rem">{{ t.pickup }} → {{ t.dropoff }}</div>
        </div>
        <div v-if="!board.unassigned.length" class="text-muted small text-center py-2">（無）</div>
      </div>
    </div>

    <!-- 各車欄(套用車行/車牌過濾) -->
    <div v-for="v in visibleVehicles" :key="v.vehicle_id" class="board-col border rounded"
         @dragover.prevent @drop="onDrop(v.vehicle_id)">
      <div class="board-head px-2 py-1 small" :class="v.conflicts ? 'bg-danger text-white' : 'bg-primary text-white'">
        <div class="d-flex justify-content-between">
          <b>{{ v.plate }}</b>
          <span><span class="badge bg-light text-dark">{{ v.trip_count }}</span>
            <span v-if="v.conflicts" class="badge bg-warning text-dark ms-1">衝突{{ v.conflicts }}</span></span>
        </div>
        <div style="font-size:.72rem">{{ v.driver || '—' }} · {{ v.fleet }}<span v-if="!v.on_duty"> · 非班表</span></div>
      </div>
      <div class="board-body p-1">
        <div v-for="t in v.trips" :key="t.order_id"
             class="trip-card border rounded p-1 mb-1"
             :class="t.conflict ? 'border-danger border-2 bg-danger-subtle' : 'bg-white'"
             draggable="true" @dragstart="onDragStart(t.order_id, v.vehicle_id)">
          <div class="d-flex justify-content-between"><b>{{ t.time }}</b>
            <span>
              <span v-if="t.welfare" class="badge bg-warning text-dark">福</span>
              <span v-if="t.status === 'ongoing'" class="badge bg-success">進</span>
            </span>
          </div>
          <div class="small">{{ t.passenger || '—' }}</div>
          <div class="text-muted" style="font-size:.72rem">{{ t.pickup }} → {{ t.dropoff }}</div>
        </div>
        <div v-if="!v.trips.length" class="text-muted small text-center py-2">（空車）</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.board-col { width: 220px; min-width: 220px; max-height: 78vh; display: flex; flex-direction: column; }
.unassigned-col { position: sticky; left: 0; z-index: 4; box-shadow: 3px 0 6px rgba(0, 0, 0, .12); }
.board-head { position: sticky; top: 0; z-index: 1; }
.board-body { overflow-y: auto; flex: 1; min-height: 60px; }
.trip-card { cursor: grab; }
.trip-card:active { cursor: grabbing; }
</style>
