<script setup>
import { onMounted, computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useOrdersStore } from '../stores/orders'
import { useVehiclesStore } from '../stores/vehicles'
import { useDriversStore } from '../stores/drivers'

const orders = useOrdersStore()
const vehicles = useVehiclesStore()
const drivers = useDriversStore()

const today = new Date().toISOString().slice(0, 10)

onMounted(() => {
  orders.fetchAll()
  vehicles.fetchAll()
  drivers.fetchAll()
})

const todayOrders = computed(
  () => orders.items.filter((o) => o.service_date === today).length
)
const activeVehicles = computed(() => vehicles.items.filter((v) => v.active).length)
const welfareVehicles = computed(
  () => vehicles.items.filter((v) => v.type === 'welfare').length
)

const cards = computed(() => [
  { label: '今日訂單', value: todayOrders.value, sub: `總計 ${orders.items.length} 筆`, to: '/orders', color: 'primary' },
  { label: '可用車輛', value: activeVehicles.value, sub: `福祉車 ${welfareVehicles.value} 台`, to: '/vehicles', color: 'success' },
  { label: '司機人數', value: drivers.items.length, sub: '點擊管理', to: '/drivers', color: 'info' },
])
</script>

<template>
  <div class="row g-3">
    <div v-for="c in cards" :key="c.label" class="col-12 col-md-6 col-xl-4">
      <RouterLink :to="c.to" class="text-decoration-none">
        <div class="card shadow-sm h-100" :class="`border-${c.color}`">
          <div class="card-body">
            <h6 class="text-muted">{{ c.label }}</h6>
            <div class="display-5 fw-bold" :class="`text-${c.color}`">{{ c.value }}</div>
            <small class="text-muted">{{ c.sub }}</small>
          </div>
        </div>
      </RouterLink>
    </div>
  </div>

  <div class="alert alert-info mt-4 mb-0">
    SmartCar 車隊派遣系統。支援 <strong>批次匯入</strong>、<strong>自動排班（VROOM）</strong>、
    <strong>路線地圖</strong> 與 <strong>動態重排</strong>。
  </div>
</template>
