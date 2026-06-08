<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import client from '../api/client'

const serviceDate = ref('2026-06-10')
const loading = ref(false)
const message = ref('')
const vehicles = ref([])

let map = null
let mapKey = ''

async function initMap() {
  const { data: cfg } = await client.get('/config')
  if (!cfg.has_map) {
    message.value = '未設定 Map8 金鑰,無法顯示地圖。'
    return false
  }
  mapKey = cfg.map8_key
  map = new maplibregl.Map({
    container: 'route-map',
    style: cfg.map8_style,
    center: [121.53, 25.04],
    zoom: 11,
    transformRequest: (url) => {
      if (url.includes('api.map8.zone') && !url.includes('key=')) {
        const sep = url.includes('?') ? '&' : '?'
        return { url: `${url}${sep}key=${mapKey}` }
      }
      return { url }
    },
  })
  map.addControl(new maplibregl.NavigationControl(), 'top-right')
  await new Promise((resolve) => map.on('load', resolve))
  return true
}

async function loadRoutes() {
  if (!map) return
  loading.value = true
  message.value = ''
  try {
    const { data } = await client.get('/dispatch/routes-geojson', {
      params: { service_date: serviceDate.value },
    })
    vehicles.value = data.vehicles || []

    if (map.getLayer('stops-label')) map.removeLayer('stops-label')
    if (map.getLayer('stops')) map.removeLayer('stops')
    if (map.getLayer('routes')) map.removeLayer('routes')
    if (map.getSource('plan')) map.removeSource('plan')

    if (!data.features.length) {
      message.value = '該日尚無排班路線,請先到訂單頁「一鍵排班」。'
      return
    }

    map.addSource('plan', { type: 'geojson', data })
    map.addLayer({
      id: 'routes', type: 'line',
      source: 'plan', filter: ['==', ['get', 'kind'], 'route'],
      paint: { 'line-color': ['get', 'color'], 'line-width': 4, 'line-opacity': 0.8 },
    })
    map.addLayer({
      id: 'stops', type: 'circle',
      source: 'plan', filter: ['!=', ['get', 'kind'], 'route'],
      paint: {
        'circle-radius': 7,
        'circle-color': ['match', ['get', 'kind'], 'pickup', '#198754', 'delivery', '#0d6efd', '#6c757d'],
        'circle-stroke-color': '#fff', 'circle-stroke-width': 2,
      },
    })
    map.addLayer({
      id: 'stops-label', type: 'symbol',
      source: 'plan', filter: ['==', ['get', 'kind'], 'pickup'],
      layout: { 'text-field': ['to-string', ['get', 'seq']], 'text-size': 11,
                'text-offset': [0, -1.2] },
      paint: { 'text-color': '#000', 'text-halo-color': '#fff', 'text-halo-width': 1.5 },
    })

    // 點擊顯示資訊
    map.on('click', 'stops', (e) => {
      const p = e.features[0].properties
      new maplibregl.Popup()
        .setLngLat(e.lngLat)
        .setHTML(`<b>${p.kind === 'pickup' ? '上車' : p.kind === 'delivery' ? '下車' : p.kind}</b>` +
                 `${p.order_id ? ' #' + p.order_id : ''}<br>${p.eta || ''}<br>${p.address || ''}`)
        .addTo(map)
    })

    // 自動縮放到所有點
    const b = new maplibregl.LngLatBounds()
    data.features.forEach((f) => {
      if (f.geometry.type === 'Point') b.extend(f.geometry.coordinates)
      else if (f.geometry.type === 'LineString') f.geometry.coordinates.forEach((c) => b.extend(c))
    })
    if (!b.isEmpty()) map.fitBounds(b, { padding: 60 })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const ok = await initMap()
  if (ok) await loadRoutes()
})
onBeforeUnmount(() => map && map.remove())
</script>

<template>
  <div class="d-flex flex-wrap gap-2 align-items-end mb-3">
    <div>
      <label class="form-label mb-1 small">服務日期</label>
      <input v-model="serviceDate" type="date" class="form-control form-control-sm" style="width: 180px" />
    </div>
    <button class="btn btn-sm btn-primary" :disabled="loading" @click="loadRoutes">
      {{ loading ? '載入中…' : '顯示路線' }}
    </button>
    <div class="d-flex flex-wrap gap-2 ms-auto">
      <span v-for="v in vehicles" :key="v.vehicle_id" class="badge" :style="{ background: v.color }">
        車#{{ v.vehicle_id }} · {{ v.stops }} 站
      </span>
    </div>
  </div>

  <div v-if="message" class="alert alert-info py-2">{{ message }}</div>

  <div id="route-map" style="height: 70vh; width: 100%; border-radius: 8px; overflow: hidden;"></div>

  <div class="small text-muted mt-2">
    🟢 上車　🔵 下車　線條顏色 = 車輛;點擊站點看詳情。底圖:Map8 圖磚,路線:自架 OSRM。
  </div>
</template>
