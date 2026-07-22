<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import client from '../api/client'
import SuggestVehicle from '../components/SuggestVehicle.vue'

// ── 狀態 ────────────────────────────────────────────
const date      = ref(new Date().toISOString().slice(0, 10))
const board     = ref(null)
const loading   = ref(false)
const reassigning = ref(false)
const error     = ref('')
const viewMode  = ref('card')   // 'card' | 'timeline'

// 篩選
const fleetFilter    = ref('')
const passengerFilter = ref('')
const plateFilter    = ref('')

// 卡片模式分頁
const PAGE_SIZE = 6
const cardPage  = ref(0)

// 時間軸
const TL_START = 6 * 60   // 06:00
const TL_END   = 19 * 60  // 19:00
const SLOT_MIN = 15
const SLOT_H   = 32        // px/15min
const tlHeaderRef = ref(null)
const tlBodyRef   = ref(null)
const tlDragOver  = ref(null)
const selectedTrip = ref(null)
const selectedVeh  = ref(null)

// 拖放
const dragging = ref(null)

// 人工指派
const manualAssign = ref({ show: false, trip: null, fromVehicleId: null, targetVehicleId: '' })

// 編輯訂單
const editModal = ref({ show: false, order_id: null, form: {} })

async function openEditOrder(trip) {
  try {
    const { data: cur } = await client.get(`/orders/${trip.order_id}`)
    // pickup_time 轉成 datetime-local 格式 (YYYY-MM-DDTHH:mm)
    let pt = cur.pickup_time || ''
    if (pt) pt = pt.slice(0, 16)  // 取前 16 字元
    editModal.value = {
      show: true,
      order_id: trip.order_id,
      form: {
        service_date: cur.service_date || '',
        pickup_time: pt,
        pickup_window_min: cur.pickup_window_min ?? 30,
        pax: cur.pax ?? 1,
        passenger_name: cur.passenger_name || '',
        passenger_phone: cur.passenger_phone || '',
        pickup_address: cur.pickup_address || '',
        dropoff_address: cur.dropoff_address || '',
        vehicle_type: cur.vehicle_type || 'normal',
        need_wheelchair: cur.need_wheelchair || false,
        allow_pool: cur.allow_pool || false,
        payment_type: cur.payment_type || '',
        order_nature: cur.order_nature || '',
        customer_region: cur.customer_region || '',
        eligibility: cur.eligibility || '',
        note: cur.note || '',
        status: cur.status || 'imported',
      },
      _raw: cur,
    }
  } catch (e) {
    alert('載入訂單失敗')
  }
}
async function submitEditOrder() {
  const { order_id, form, _raw } = editModal.value
  try {
    await client.put(`/orders/${order_id}`, { ..._raw, ...form })
    editModal.value.show = false
    await load()
  } catch (e) {
    alert(e.response?.data?.detail || '修改失敗')
  }
}

// 取消訂單
async function cancelOrder(trip) {
  if (!confirm(`確定取消「${trip.passenger}」${trip.pickup_time || trip.time} 的訂單？\n取消後將清除派遣指派。`)) return
  try {
    await client.post(`/orders/${trip.order_id}/cancel`)
    await load()
  } catch (e) {
    alert(e.response?.data?.detail || '取消失敗')
  }
}

// AI 建議
const suggestOrderObj = ref(null)

// ── 計算屬性 ──────────────────────────────────────
const fleets = computed(() => {
  if (!board.value) return []
  return [...new Set(board.value.vehicles.map(v => v.fleet).filter(Boolean))].sort()
})

const filteredVehicles = computed(() => {
  if (!board.value?.vehicles) return []
  const pass = passengerFilter.value.trim()
  const pl   = plateFilter.value.trim().toLowerCase()
  return board.value.vehicles.filter(v => {
    if (fleetFilter.value && v.fleet !== fleetFilter.value) return false
    if (pl && !(v.plate || '').toLowerCase().includes(pl)) return false
    if (pass) return (v.trips || []).some(t => (t.passenger || '').includes(pass))
    return true
  })
})

const filteredUnassigned = computed(() =>
  [...(board.value?.unassigned ?? [])].sort((a, b) => {
    const ta = a.pickup_time || a.time || ''
    const tb = b.pickup_time || b.time || ''
    return ta.localeCompare(tb)
  })
)

const pagedVehicles = computed(() =>
  filteredVehicles.value.slice(cardPage.value * PAGE_SIZE, (cardPage.value + 1) * PAGE_SIZE)
)

watch([fleetFilter, passengerFilter, plateFilter], () => { cardPage.value = 0 })

// ── 時間軸工具 ────────────────────────────────────
const timeSlots = computed(() => {
  const slots = []
  for (let m = TL_START; m < TL_END; m += SLOT_MIN) {
    const h = Math.floor(m / 60), mm = m % 60
    slots.push({ label: `${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}`, isHour: mm === 0, mins: m })
  }
  return slots
})

function hmToMins(hm) {
  if (!hm) return null
  const [h, m] = hm.split(':').map(Number)
  return h * 60 + m
}
function minsToTop(mins) {
  return (Math.max(0, mins - TL_START) / SLOT_MIN) * SLOT_H
}
function durationH(start, end) {
  if (end == null || end <= start) return SLOT_H * 3
  return (Math.max(SLOT_MIN, end - start) / SLOT_MIN) * SLOT_H
}
function tripStyle(trip) {
  const start = hmToMins(trip.eta || trip.pickup_time || trip.time)
  if (start == null) return { display: 'none' }
  const end = hmToMins(trip.dropoff_time)
  return { top: minsToTop(start) + 'px', height: durationH(start, end) + 'px' }
}
function unassignedStyle(item, idx) {
  const start = hmToMins(item.pickup_time || item.time)
  if (start == null) return { display: 'none' }
  return { top: minsToTop(start) + 'px', height: SLOT_H * 2 + 'px', left: (idx % 2) * 50 + '%', width: '50%' }
}
function tripClass(trip) {
  if (trip.conflict) return 'chip-conflict'
  const late = trip.trip_index !== 0 && isLate(trip)   // 第一趟不顯示遲到
  if (late) return (trip.need_welfare || trip.welfare) ? 'chip-welfare chip-late-border' : 'chip-normal chip-late-border'
  if (trip.need_welfare || trip.welfare) return 'chip-welfare'
  if (trip.is_pool || trip.pooled) return 'chip-pool'
  return 'chip-normal'
}
function isLate(trip) {
  const sched = hmToMins(trip.pickup_time || trip.time)
  const actual = hmToMins(trip.eta)
  return sched != null && actual != null && (actual - sched) > 15
}
function lateMin(trip) {
  return hmToMins(trip.eta) - hmToMins(trip.pickup_time || trip.time)
}
function tripTooltip(trip) {
  const late = isLate(trip) ? ` ⚠遲${lateMin(trip)}分` : ''
  return `${trip.passenger} | 預約${trip.pickup_time || trip.time} ETA${trip.eta}${late}\n↑ ${trip.pickup_addr || trip.pickup}\n↓ ${trip.dropoff_addr || trip.dropoff}`
}
function shortName(name) {
  if (!name) return ''
  return name.length > 4 ? name.slice(0, 3) + '…' : name
}
function shortAddr(addr) {
  if (!addr) return ''
  const m = addr.match(/[市縣](.{2,3}[區鄉鎮市])/)
  return m ? m[1] : addr.slice(0, 5)
}
function onTlScroll() {
  if (tlHeaderRef.value && tlBodyRef.value)
    tlHeaderRef.value.scrollLeft = tlBodyRef.value.scrollLeft
}
function selectTrip(trip, veh) {
  selectedTrip.value = trip
  selectedVeh.value  = veh
}

// ── 卡片模式：趟次間距 + 距離 ────────────────────
function tripGap(prev, next) {
  const p = hmToMins(prev.dropoff_time || prev.pickup_time || prev.time)
  const n = hmToMins(next.pickup_time || next.time)
  if (p == null || n == null) return null
  return n - p
}
function haversineKm(lng1, lat1, lng2, lat2) {
  if (lng1 == null || lat1 == null || lng2 == null || lat2 == null) return null
  const R = 6371, toR = x => x * Math.PI / 180
  const dLat = toR(lat2 - lat1), dLng = toR(lng2 - lng1)
  const a = Math.sin(dLat/2)**2 + Math.cos(toR(lat1)) * Math.cos(toR(lat2)) * Math.sin(dLng/2)**2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a))
}
function tripDistance(prev, next) {
  const km = haversineKm(prev.dropoff_lng, prev.dropoff_lat, next.pickup_lng, next.pickup_lat)
  if (km == null) return null
  return km < 1 ? `${Math.round(km*1000)}m` : `${km.toFixed(1)}km`
}
function gapColor(gap) {
  if (gap < 0)    return '#dc3545'
  if (gap < 10)   return '#fd7e14'
  if (gap <= 15)  return '#198754'
  return '#6c757d'
}
function gapIdeal(gap) { return gap != null && gap >= 10 && gap <= 15 }

// ── 資料載入 ──────────────────────────────────────
async function load() {
  loading.value = true; error.value = ''; selectedTrip.value = null
  try {
    const params = { service_date: date.value, source: 'human' }
    if (fleetFilter.value) params.fleet = fleetFilter.value
    const { data } = await client.get('/dispatch/board', { params })
    board.value = data
    cardPage.value = 0
  } catch (e) {
    error.value = e?.response?.data?.detail || '讀取失敗'
  } finally { loading.value = false }
}

onMounted(async () => {
  try {
    const { data } = await client.get('/dispatch/board/meta')
    if (data.latest_date) date.value = data.latest_date
  } catch (e) { /* 忽略 */ }
  await load()
})

// ── 拖放 ─────────────────────────────────────────
function onDragStart(evt, orderId, fromVid) {
  dragging.value = { order_id: orderId, from_vehicle_id: fromVid }
  evt.dataTransfer.effectAllowed = 'move'
}
async function onDropVehicle(evt, vehicleId) {
  evt.preventDefault()
  if (!dragging.value || dragging.value.from_vehicle_id === vehicleId) return
  await doReassign(dragging.value.order_id, vehicleId)
}
async function onDropUnassigned(evt) {
  evt.preventDefault()
  if (!dragging.value || dragging.value.from_vehicle_id === null) return
  await doReassign(dragging.value.order_id, null)
}
async function doReassign(orderId, vehicleId) {
  reassigning.value = true
  try {
    await client.post('/dispatch/board/reassign', {
      order_id: orderId, vehicle_id: vehicleId, service_date: date.value
    })
    await load()
  } catch (e) {
    error.value = e?.response?.data?.detail || '重指派失敗'
  } finally { reassigning.value = false; dragging.value = null; tlDragOver.value = null }
}

// ── 人工指派 Modal ────────────────────────────────
function openManualAssign(item, veh) {
  manualAssign.value = {
    show: true,
    trip: { order_id: item.order_id, passenger: item.passenger,
            pickup_time: item.pickup_time || item.time,
            pickup_addr: item.pickup_addr || item.pickup },
    fromVehicleId: veh?.vehicle_id ?? null,
    targetVehicleId: String(veh?.vehicle_id ?? ''),
  }
}
async function submitManualAssign() {
  const { trip, targetVehicleId } = manualAssign.value
  const toId = targetVehicleId === '' ? null : Number(targetVehicleId)
  manualAssign.value.show = false
  await doReassign(trip.order_id, toId)
}

// ── AI 建議 ───────────────────────────────────────
function openSuggest(item) {
  suggestOrderObj.value = {
    id: item.order_id, fleet: item.fleet, passenger: item.passenger,
    pickup: item.pickup_addr || item.pickup, dropoff: item.dropoff_addr || item.dropoff,
    welfare: item.need_welfare || item.welfare, time: item.pickup_time || item.time,
  }
}
async function onAssigned() { suggestOrderObj.value = null; await load() }
</script>

<template>
  <div>
    <!-- ── 工具列 ── -->
    <div class="dispatch-toolbar mb-3">
      <h5 class="dispatch-title mb-0">🧲 派遣看板</h5>
      <div class="dispatch-controls">
        <input v-model="date" type="date" class="form-control form-control-sm" style="width:150px" @change="load" />
        <select v-if="fleets.length > 1" v-model="fleetFilter" class="form-select form-select-sm" style="width:120px">
          <option value="">全部車行</option>
          <option v-for="f in fleets" :key="f" :value="f">{{ f }}</option>
        </select>
        <input v-model="passengerFilter" type="text" class="form-control form-control-sm" placeholder="乘客姓名" style="width:100px" />
        <input v-model="plateFilter" type="text" class="form-control form-control-sm" placeholder="車號" style="width:90px" />
        <button class="btn btn-sm btn-primary" :disabled="loading" @click="load">
          <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>載入
        </button>
        <!-- 視圖切換 -->
        <div class="btn-group btn-group-sm ms-2">
          <button class="btn" :class="viewMode==='card' ? 'btn-secondary' : 'btn-outline-secondary'" @click="viewMode='card'">
            ☰ 卡片
          </button>
          <button class="btn" :class="viewMode==='timeline' ? 'btn-secondary' : 'btn-outline-secondary'" @click="viewMode='timeline'">
            📅 時間軸
          </button>
        </div>
        <span v-if="board" class="small text-muted ms-2">
          {{ filteredVehicles.length }}/{{ board.vehicles.length }} 車 · 未指派 {{ board.unassigned_count }}
        </span>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
    <div v-if="board && !board.vehicles.length && !board.unassigned.length" class="alert alert-info py-2">
      <b>{{ date }}</b> 無排班/派遣車輛。請改選有資料的日期，或先到「訂單管理」按「🚀 一鍵排班」。
    </div>

    <!-- ════════ 卡片模式 ════════ -->
    <template v-if="board && viewMode==='card'">
      <!-- 分頁導覽 -->
      <div class="d-flex align-items-center justify-content-between mb-2">
        <button class="btn btn-sm btn-outline-secondary" :disabled="cardPage===0" @click="cardPage--">‹ 上頁</button>
        <span class="small text-muted">
          車輛 {{ filteredVehicles.length ? cardPage*PAGE_SIZE+1 : 0 }}–{{ Math.min((cardPage+1)*PAGE_SIZE, filteredVehicles.length) }} / {{ filteredVehicles.length }} 台
        </span>
        <button class="btn btn-sm btn-outline-secondary" :disabled="(cardPage+1)*PAGE_SIZE >= filteredVehicles.length" @click="cardPage++">下頁 ›</button>
      </div>

      <div class="d-flex gap-2" style="overflow-x:auto; align-items:flex-start; min-height:70vh">
        <!-- 未指派欄 -->
        <div class="card flex-shrink-0" style="width:210px; min-height:200px;"
             @dragover.prevent @drop="onDropUnassigned">
          <div class="card-header bg-secondary text-white py-2 fw-bold small">
            未指派 <span class="badge bg-light text-dark">{{ filteredUnassigned.length }}</span>
          </div>
          <div class="card-body p-2 d-flex flex-column gap-2" style="overflow-y:auto;max-height:75vh">
            <div v-for="item in filteredUnassigned" :key="item.order_id"
                 class="trip-card border rounded p-2 bg-white"
                 draggable="true" @dragstart="onDragStart($event, item.order_id, null)">
              <div class="d-flex align-items-start justify-content-between">
                <span class="fw-bold small">{{ item.pickup_time || item.time }}</span>
                <span>
                  <span v-if="item.need_welfare||item.welfare" class="badge bg-warning text-dark">⚕ 福祉車</span>
                  <span v-else class="badge bg-secondary">一般車</span>
                  <button class="btn btn-xs btn-outline-warning ms-1 py-0 px-1" style="font-size:.68rem"
                          @click.stop="openSuggest(item)">💡</button>
                </span>
              </div>
              <div class="small text-truncate">
                <span v-if="item.is_standby" class="badge bg-secondary me-1" style="font-size:.62rem">候補</span>{{ item.passenger || '—' }}
              </div>
              <div class="text-muted text-truncate" style="font-size:.72rem">↑ {{ item.pickup_addr || item.pickup }}</div>
              <div class="text-muted text-truncate" style="font-size:.72rem">↓ {{ item.dropoff_addr || item.dropoff }}</div>
              <div class="mt-1 d-flex justify-content-end gap-1">
                <button class="btn btn-xs btn-outline-secondary py-0 px-1" style="font-size:.68rem"
                        @click.stop="openManualAssign(item, { vehicle_id: null })">↔ 指派</button>
                <button class="btn btn-xs btn-outline-primary py-0 px-1" style="font-size:.68rem"
                        @click.stop="openEditOrder(item)">✏️ 修改</button>
                <button class="btn btn-xs btn-outline-danger py-0 px-1" style="font-size:.68rem"
                        @click.stop="cancelOrder(item)">✕ 取消</button>
              </div>
            </div>
            <div v-if="!filteredUnassigned.length" class="text-muted small text-center py-3">無未指派</div>
          </div>
        </div>

        <!-- 車輛欄 -->
        <div v-for="veh in pagedVehicles" :key="veh.col_key || veh.vehicle_id"
             class="card flex-shrink-0" style="width:225px; min-height:200px;"
             :class="{ 'border-danger border-2': veh.has_conflict }"
             @dragover.prevent @drop="onDropVehicle($event, veh.vehicle_id)">
          <div class="card-header py-2 small"
               :class="veh.has_conflict ? 'bg-danger text-white' : veh.vehicle_type==='welfare' ? 'bg-warning text-dark' : 'bg-primary text-white'">
            <div class="d-flex justify-content-between align-items-center">
              <span class="fw-bold">{{ veh.plate }}</span>
              <span>
                <span class="badge bg-light text-dark">{{ veh.trip_count }}趟</span>
                <span v-if="veh.has_conflict" class="badge bg-warning text-dark ms-1">⚠衝突</span>
              </span>
            </div>
            <div style="font-size:.7rem;opacity:.9">
              {{ veh.driver || '—' }}<span v-if="!veh.on_duty" class="ms-1 opacity-75">非班表</span>
            </div>
          </div>
          <div class="card-body p-2 d-flex flex-column gap-1" style="overflow-y:auto;max-height:72vh">
            <template v-for="(trip, idx) in veh.trips" :key="trip.order_id">
              <!-- 趟次間距 -->
              <div v-if="idx > 0 && tripGap(veh.trips[idx-1], trip) !== null"
                   class="d-flex justify-content-between align-items-center px-1 py-0"
                   style="font-size:0.62rem; border-left:2px solid; margin:2px 0;"
                   :style="{ borderColor: gapColor(tripGap(veh.trips[idx-1], trip)) }">
                <span :style="{ color: gapColor(tripGap(veh.trips[idx-1], trip)),
                                fontWeight: gapIdeal(tripGap(veh.trips[idx-1], trip)) ? '600' : 'normal' }">
                  空閑：{{ tripGap(veh.trips[idx-1], trip) >= 0 ? '+' : '' }}{{ tripGap(veh.trips[idx-1], trip) }}分
                  <span v-if="gapIdeal(tripGap(veh.trips[idx-1], trip))">✓</span>
                </span>
                <span v-if="tripDistance(veh.trips[idx-1], trip)" class="text-muted">
                  距離：{{ tripDistance(veh.trips[idx-1], trip) }}
                </span>
              </div>
              <!-- 趟次卡片 -->
              <div class="trip-card border rounded p-2"
                   :class="trip.conflict ? 'border-danger bg-danger-subtle' : (trip.is_pool||trip.pooled) ? 'border-info bg-info-subtle' : 'bg-white'"
                   draggable="true" @dragstart="onDragStart($event, trip.order_id, veh.vehicle_id)">
                <div class="d-flex justify-content-between align-items-start">
                  <div>
                    <div class="fw-bold small">預約 {{ trip.pickup_time || trip.time }}</div>
                    <div class="text-muted" style="font-size:.72rem">抵達 {{ trip.dropoff_time || '—' }}</div>
                  </div>
                  <span class="d-flex flex-wrap gap-1 justify-content-end">
                    <span v-if="trip.is_pool||trip.pooled" class="badge bg-info text-dark">共乘</span>
                    <span v-if="trip.need_welfare||trip.welfare" class="badge bg-warning text-dark">⚕ 福祉車</span>
                    <span v-else class="badge bg-secondary">一般車</span>
                    <span v-if="trip.status==='ongoing'" class="badge bg-success">進行中</span>
                    <span v-if="idx > 0 && isLate(trip)" class="badge bg-danger ms-1">遲{{ lateMin(trip) }}分</span>
                  </span>
                </div>
                <div class="small text-truncate" :title="trip.passenger">
                  <span v-if="trip.is_standby" class="badge bg-secondary me-1" style="font-size:.62rem">候補</span>{{ trip.passenger || '—' }}
                </div>
                <div class="text-muted text-truncate" style="font-size:.72rem">↑ {{ trip.pickup_addr || trip.pickup }}</div>
                <div class="text-muted text-truncate" style="font-size:.72rem">↓ {{ trip.dropoff_addr || trip.dropoff }}</div>
                <div v-if="trip.conflict" class="text-danger" style="font-size:.7rem">⚠ 時間衝突</div>
                <div class="mt-1 d-flex justify-content-end gap-1">
                  <button class="btn btn-xs btn-outline-secondary py-0 px-1" style="font-size:.68rem"
                          @click.stop="openManualAssign(trip, veh)">↔ 指派</button>
                  <button class="btn btn-xs btn-outline-primary py-0 px-1" style="font-size:.68rem"
                          @click.stop="openEditOrder(trip)">✏️ 修改</button>
                  <button class="btn btn-xs btn-outline-danger py-0 px-1" style="font-size:.68rem"
                          @click.stop="cancelOrder(trip)">✕ 取消</button>
                </div>
              </div>
            </template>
            <div v-if="!veh.trips.length" class="text-muted small text-center py-3">空車</div>
          </div>
        </div>
      </div>
    </template>

    <!-- ════════ 時間軸模式 ════════ -->
    <div v-if="board && viewMode==='timeline'" class="timeline-wrap">
      <!-- 圖例 -->
      <div class="timeline-legend mb-2">
        <span class="legend-chip chip-normal">一般</span>
        <span class="legend-chip chip-welfare">福祉</span>
        <span class="legend-chip chip-late">遲到&gt;15分</span>
        <span class="legend-chip chip-conflict">時間衝突</span>
        <span class="legend-chip chip-pool">🤝共乘</span>
        <span class="ms-3 text-muted small">每格 = 15 分鐘</span>
      </div>

      <!-- 固定表頭（水平由 JS 同步） -->
      <div class="tl-header-row" ref="tlHeaderRef">
        <div class="tl-corner"></div>
        <!-- 未指派表頭 -->
        <div class="tl-head-cell header-unassigned">
          <div class="fw-bold" style="font-size:.8rem">未指派</div>
          <div style="font-size:.7rem">{{ board.unassigned.length }} 筆</div>
        </div>
        <!-- 車輛表頭 -->
        <div v-for="veh in filteredVehicles" :key="veh.col_key || veh.vehicle_id"
             class="tl-head-cell"
             :class="veh.vehicle_type==='welfare' ? 'header-welfare' : 'header-normal'">
          <div class="fw-bold" style="font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            {{ veh.driver || veh.plate }}
          </div>
          <div style="font-size:.68rem;opacity:.85">
            {{ veh.plate }}<span v-if="veh.has_conflict" class="ms-1">⚠</span>
          </div>
          <div style="font-size:.65rem;opacity:.75">{{ veh.fleet }} · {{ veh.trip_count }}趟</div>
        </div>
      </div>

      <!-- 可捲動主體 -->
      <div class="tl-body-scroll" ref="tlBodyRef" @scroll="onTlScroll">
        <!-- 時間軸 -->
        <div class="tl-time-axis">
          <div v-for="slot in timeSlots" :key="slot.label" class="tl-slot-label" :class="{ 'tl-hour-mark': slot.isHour }">
            <span v-if="slot.isHour">{{ slot.label }}</span>
          </div>
        </div>

        <!-- 未指派欄主體 -->
        <div class="tl-veh-body"
             :class="{ 'tl-drop-hover-warn': tlDragOver === 'unassigned' }"
             @dragover.prevent="tlDragOver='unassigned'"
             @dragleave="tlDragOver=null"
             @drop="onDropUnassigned($event); tlDragOver=null">
          <div v-for="slot in timeSlots" :key="slot.label" class="tl-slot-bg" :class="{ 'tl-hour-bg': slot.isHour }"></div>
          <div v-for="(item, idx) in board.unassigned" :key="item.order_id"
               class="tl-trip-block chip-unassigned"
               :class="{ 'tl-dragging': dragging?.order_id === item.order_id }"
               :style="unassignedStyle(item, idx)"
               :title="`${item.passenger} ${item.pickup_time||item.time} ${item.pickup_addr||item.pickup}`"
               draggable="true"
               @dragstart="onDragStart($event, item.order_id, null)"
               @dragend="dragging=null; tlDragOver=null">
            <div class="tl-trip-time">{{ item.pickup_time || item.time }}</div>
            <div class="tl-trip-name">{{ shortName(item.passenger) }}</div>
          </div>
        </div>

        <!-- 車輛主體欄 -->
        <div v-for="veh in filteredVehicles" :key="veh.col_key || veh.vehicle_id"
             class="tl-veh-body"
             :class="{ 'tl-drop-hover': tlDragOver === veh.vehicle_id }"
             @dragover.prevent="tlDragOver=veh.vehicle_id"
             @dragleave="tlDragOver=null"
             @drop="onDropVehicle($event, veh.vehicle_id); tlDragOver=null">
          <div v-for="slot in timeSlots" :key="slot.label" class="tl-slot-bg" :class="{ 'tl-hour-bg': slot.isHour }"></div>
          <div v-for="trip in veh.trips" :key="trip.order_id"
               class="tl-trip-block"
               :class="[tripClass(trip), { 'tl-dragging': dragging?.order_id === trip.order_id }]"
               :style="tripStyle(trip)"
               :title="tripTooltip(trip)"
               draggable="true"
               @dragstart="onDragStart($event, trip.order_id, veh.vehicle_id)"
               @dragend="dragging=null; tlDragOver=null"
               @click.stop="selectTrip(trip, veh)">
            <div class="tl-trip-time">{{ trip.eta || trip.pickup_time || trip.time }}</div>
            <div class="tl-trip-name">{{ shortName(trip.passenger) }}</div>
            <div class="tl-trip-addr">{{ shortAddr(trip.pickup_addr || trip.pickup) }}</div>
            <span v-if="trip.trip_index !== 0 && isLate(trip)" class="tl-late-badge">遲{{ lateMin(trip) }}分</span>
          </div>
        </div>
      </div>

      <!-- 趟次詳情面板 -->
      <div v-if="selectedTrip" class="tl-detail-panel">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <strong>趟次詳情</strong>
          <button class="btn btn-sm btn-close" @click="selectedTrip=null"></button>
        </div>
        <div class="small">
          <div><b>乘客：</b>{{ selectedTrip.passenger }}（{{ selectedTrip.pax }}人）</div>
          <div><b>預約：</b>{{ selectedTrip.pickup_time || selectedTrip.time }}</div>
          <div><b>ETA：</b>{{ selectedTrip.eta || '—' }}</div>
          <div v-if="selectedTrip.trip_index !== 0 && isLate(selectedTrip)" class="text-danger"><b>遲到：</b>{{ lateMin(selectedTrip) }} 分</div>
          <div><b>下車：</b>{{ selectedTrip.dropoff_time || '—' }}</div>
          <div class="mt-1"><b>↑</b> {{ selectedTrip.pickup_addr || selectedTrip.pickup }}</div>
          <div><b>↓</b> {{ selectedTrip.dropoff_addr || selectedTrip.dropoff }}</div>
          <div class="mt-1">
            <span v-if="selectedTrip.is_pool||selectedTrip.pooled" class="badge bg-info me-1">🤝共乘</span>
            <span v-if="selectedTrip.conflict" class="badge bg-danger me-1">⚠衝突</span>
            <span v-if="selectedTrip.need_welfare||selectedTrip.welfare" class="badge bg-warning text-dark">♿福祉</span>
          </div>
          <div class="mt-2 text-muted small">{{ selectedVeh?.plate }} {{ selectedVeh?.driver }}</div>
          <div class="mt-2">
            <button class="btn btn-xs btn-outline-primary py-0 px-2" style="font-size:.72rem"
                    @click="openManualAssign(selectedTrip, selectedVeh); selectedTrip=null">✏️ 重新指派</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ════════ 人工指派 Modal ════════ -->
    <div v-if="manualAssign.show" class="modal d-block" style="background:rgba(0,0,0,.45);z-index:1050">
      <div class="modal-dialog modal-sm">
        <div class="modal-content">
          <div class="modal-header py-2">
            <h6 class="modal-title mb-0">人工指派 — {{ manualAssign.trip?.passenger }}</h6>
            <button class="btn-close" @click="manualAssign.show=false"></button>
          </div>
          <div class="modal-body py-2">
            <div class="text-muted small mb-2">
              {{ manualAssign.trip?.pickup_time }} ↑ {{ (manualAssign.trip?.pickup_addr || '').slice(0,20) }}…
            </div>
            <label class="form-label small mb-1">選擇車輛</label>
            <select v-model="manualAssign.targetVehicleId" class="form-select form-select-sm">
              <option value="">— 移至未指派 —</option>
              <option v-for="v in board.vehicles" :key="v.vehicle_id" :value="String(v.vehicle_id)">
                {{ v.plate }} {{ v.driver }} ({{ v.trip_count }}趟)
              </option>
            </select>
          </div>
          <div class="modal-footer py-2">
            <button class="btn btn-sm btn-secondary" @click="manualAssign.show=false">取消</button>
            <button class="btn btn-sm btn-primary" :disabled="reassigning" @click="submitManualAssign">
              <span v-if="reassigning" class="spinner-border spinner-border-sm me-1"></span>確認
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ════════ 編輯訂單 Modal ════════ -->
    <div v-if="editModal.show" class="modal d-block" style="background:rgba(0,0,0,.45);z-index:1055">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header py-2">
            <h6 class="modal-title mb-0">✏️ 修改訂單 #{{ editModal.order_id }}</h6>
            <button class="btn-close" @click="editModal.show=false"></button>
          </div>
          <div class="modal-body py-2" style="max-height:70vh;overflow-y:auto">
            <div class="row g-2">
              <div class="col-6">
                <label class="form-label small mb-1">服務日期 *</label>
                <input v-model="editModal.form.service_date" type="date" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">預約上車時間 *</label>
                <input v-model="editModal.form.pickup_time" type="datetime-local" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">時間彈性(分)</label>
                <input v-model.number="editModal.form.pickup_window_min" type="number" min="0" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">人數</label>
                <input v-model.number="editModal.form.pax" type="number" min="1" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">乘客姓名</label>
                <input v-model="editModal.form.passenger_name" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">聯絡電話</label>
                <input v-model="editModal.form.passenger_phone" class="form-control form-control-sm" />
              </div>
              <div class="col-12">
                <label class="form-label small mb-1">上車地址 *</label>
                <input v-model="editModal.form.pickup_address" class="form-control form-control-sm" />
              </div>
              <div class="col-12">
                <label class="form-label small mb-1">下車地址 *</label>
                <input v-model="editModal.form.dropoff_address" class="form-control form-control-sm" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">車種</label>
                <select v-model="editModal.form.vehicle_type" class="form-select form-select-sm">
                  <option value="normal">一般車</option>
                  <option value="welfare">福祉車</option>
                </select>
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">狀態</label>
                <select v-model="editModal.form.status" class="form-select form-select-sm">
                  <option value="imported">已匯入</option>
                  <option value="scheduled">已排班</option>
                  <option value="ongoing">進行中</option>
                  <option value="done">完成</option>
                  <option value="canceled">取消</option>
                </select>
              </div>
              <div class="col-12 d-flex gap-4">
                <div class="form-check">
                  <input v-model="editModal.form.need_wheelchair" class="form-check-input" type="checkbox" id="eWheel" />
                  <label class="form-check-label small" for="eWheel">需要輪椅</label>
                </div>
                <div class="form-check">
                  <input v-model="editModal.form.allow_pool" class="form-check-input" type="checkbox" id="ePool" />
                  <label class="form-check-label small" for="ePool">可共乘</label>
                </div>
              </div>
              <div class="col-4">
                <label class="form-label small mb-1">付款方式</label>
                <select v-model="editModal.form.payment_type" class="form-select form-select-sm">
                  <option value="">—未設定—</option>
                  <option value="subsidy">補助</option>
                  <option value="self">自費</option>
                </select>
              </div>
              <div class="col-4">
                <label class="form-label small mb-1">性質</label>
                <input v-model="editModal.form.order_nature" class="form-control form-control-sm" placeholder="就醫、洗腎…" />
              </div>
              <div class="col-4">
                <label class="form-label small mb-1">客戶所在地區</label>
                <input v-model="editModal.form.customer_region" class="form-control form-control-sm" placeholder="例：信義區" />
              </div>
              <div class="col-6">
                <label class="form-label small mb-1">身份資格</label>
                <select v-model="editModal.form.eligibility" class="form-select form-select-sm">
                  <option value="">—未設定—</option>
                  <option value="一般">一般</option>
                  <option value="低收入戶">低收入戶</option>
                  <option value="中低收9%">中低收9%</option>
                  <option value="偏鄉低收2400">偏鄉低收2400</option>
                </select>
              </div>
              <div class="col-12">
                <label class="form-label small mb-1">備註</label>
                <textarea v-model="editModal.form.note" class="form-control form-control-sm" rows="2"></textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer py-2">
            <button class="btn btn-sm btn-secondary" @click="editModal.show=false">取消</button>
            <button class="btn btn-sm btn-primary" @click="submitEditOrder">儲存</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 重指派 loading overlay -->
    <div v-if="reassigning" class="position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center"
         style="background:rgba(0,0,0,.3);z-index:9999">
      <div class="spinner-border text-light" style="width:3rem;height:3rem"></div>
    </div>

    <!-- AI 建議 -->
    <SuggestVehicle :order="suggestOrderObj" :service-date="date"
                    @close="suggestOrderObj=null" @assigned="onAssigned" />
  </div>
</template>

<style scoped>
/* 工具列 */
.dispatch-toolbar { display:flex; align-items:center; justify-content:space-between; gap:.75rem; background:#f8f9fa; border:1px solid #dee2e6; border-radius:8px; padding:.6rem 1rem; flex-wrap:wrap; }
.dispatch-title { white-space:nowrap; }
.dispatch-controls { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; }
.trip-card { cursor:grab; user-select:none; font-size:.8rem; }
.trip-card:active { cursor:grabbing; }

/* 時間軸容器 */
.timeline-wrap { position:relative; }
.tl-header-row { display:flex; overflow:hidden; border:1px solid #dee2e6; border-bottom:2px solid #c0cfe0; border-radius:6px 6px 0 0; background:#fff; flex-shrink:0; }
.tl-corner { flex-shrink:0; width:52px; height:64px; background:#f8f9fa; border-right:2px solid #dee2e6; }
.tl-head-cell { flex-shrink:0; width:152px; height:64px; padding:6px 8px; overflow:hidden; border-right:1px solid rgba(255,255,255,.15); }
.tl-body-scroll { display:flex; overflow:auto; max-height:calc(100vh - 230px); border:1px solid #dee2e6; border-top:none; border-radius:0 0 6px 6px; background:#fff; }
.tl-time-axis { flex-shrink:0; width:52px; border-right:2px solid #dee2e6; background:#f8f9fa; position:sticky; left:0; z-index:5; }
.tl-veh-body { flex-shrink:0; width:152px; border-right:1px solid #e9ecef; position:relative; }
.header-normal    { background:#4472C4; color:#fff; }
.header-welfare   { background:#FF8C00; color:#fff; }
.header-unassigned { background:#6c757d; color:#fff; }
.tl-slot-bg { height:32px; border-bottom:1px solid #f0f0f0; }
.tl-hour-bg { border-bottom:1px solid #ccc; background:#fafafa; }
.tl-slot-label { height:32px; display:flex; align-items:center; justify-content:flex-end; padding-right:6px; font-size:.65rem; color:#888; border-bottom:1px solid #f0f0f0; }
.tl-hour-mark { color:#333; font-weight:700; font-size:.72rem; border-bottom:1px solid #ccc; }
.tl-trip-block { position:absolute; left:2px; right:2px; border-radius:4px; padding:2px 5px; cursor:pointer; overflow:hidden; font-size:.68rem; line-height:1.3; transition:opacity .15s; z-index:2; }
.tl-trip-block:hover { opacity:.85; box-shadow:0 2px 6px rgba(0,0,0,.2); }
.tl-trip-time { font-weight:700; font-size:.7rem; }
.tl-trip-name { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tl-trip-addr { font-size:.62rem; opacity:.85; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tl-dragging { opacity:.35 !important; }
.tl-drop-hover { background:rgba(74,144,217,.08) !important; outline:2px dashed #4a90d9; outline-offset:-2px; }
.tl-drop-hover-warn { background:rgba(255,140,0,.08) !important; outline:2px dashed #ff8c00; outline-offset:-2px; }
.tl-late-badge { display:inline-block; background:rgba(0,0,0,.25); border-radius:3px; padding:0 3px; font-size:.6rem; margin-top:2px; }
/* 色塊 */
.chip-normal    { background:#4472C4; color:#fff; border:1px solid #2d5ba0; }
.chip-welfare   { background:#FF8C00; color:#fff; border:1px solid #cc7000; }
.chip-conflict  { background:#dc3545; color:#fff; border:2px solid #a71d2a; }
.chip-pool      { background:#0dcaf0; color:#fff; border:1px solid #0aa5c5; }
.chip-late-border { border:2px solid #ffc107 !important; }
.chip-unassigned { background:#adb5bd; color:#fff; border:1px solid #868e96; }
/* 圖例 */
.timeline-legend { display:flex; align-items:center; gap:.5rem; flex-wrap:wrap; }
.legend-chip { display:inline-block; padding:2px 8px; border-radius:4px; font-size:.72rem; color:#fff; }
.legend-chip.chip-normal   { background:#4472C4; }
.legend-chip.chip-welfare  { background:#FF8C00; }
.legend-chip.chip-late     { background:#4472C4; border:2px solid #ffc107; }
.legend-chip.chip-conflict { background:#dc3545; }
.legend-chip.chip-pool     { background:#0dcaf0; }
/* 詳情面板 */
.tl-detail-panel { position:fixed; bottom:24px; right:24px; width:300px; background:#fff; border:1px solid #dee2e6; border-radius:8px; box-shadow:0 4px 16px rgba(0,0,0,.15); padding:12px 14px; z-index:100; }
</style>
