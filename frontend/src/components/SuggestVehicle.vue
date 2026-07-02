<script setup>
import { ref, watch } from 'vue'
import client from '../api/client'

const props = defineProps({
  order: { type: Object, default: null },      // { id, fleet, passenger, pickup, dropoff, welfare, time }
  serviceDate: { type: String, default: '' },
  allowAssign: { type: Boolean, default: true },  // false=唯讀建議(不顯示採用,如 done 日未派分析)
})
const emit = defineEmits(['close', 'assigned'])

const scope = ref('own')                        // own | company
const data = ref(null)
const loading = ref(false)
const error = ref('')
const assigning = ref(null)

async function load() {
  if (!props.order) return
  loading.value = true; error.value = ''; data.value = null
  try {
    const { data: d } = await client.get('/dispatch/vehicle-suggest', {
      params: {
        order_id: props.order.id,
        ...(props.serviceDate ? { service_date: props.serviceDate } : {}),
        fleet_scope: scope.value, top_n: 8,
      },
      timeout: 60000,
    })
    data.value = d
  } catch (e) {
    error.value = e.response?.data?.detail || '取得建議失敗'
  } finally {
    loading.value = false
  }
}

async function adopt(c) {
  if (!c.feasible && !confirm(`「${c.plate}」目前判定不可行(${c.reason || '未知'}),仍要指派?`)) return
  assigning.value = c.vehicle_id
  error.value = ''
  try {
    await client.post(`/orders/${props.order.id}/assign`, null, { params: { vehicle_id: c.vehicle_id } })
    emit('assigned', { order_id: props.order.id, vehicle_id: c.vehicle_id, plate: c.plate })
  } catch (e) {
    error.value = e.response?.data?.detail || '指派失敗'
  } finally {
    assigning.value = null
  }
}

// 開啟(order 由 null→有值)或切換車隊範圍時重新載入
watch(() => props.order, (o) => { if (o) { scope.value = 'own'; load() } }, { immediate: true })
watch(scope, () => { if (props.order) load() })
</script>

<template>
  <div v-if="order" class="sv-backdrop" @click.self="emit('close')">
    <div class="sv-modal card shadow">
      <div class="card-header d-flex justify-content-between align-items-center py-2">
        <span class="fw-semibold">💡 建議車輛</span>
        <button class="btn-close" @click="emit('close')"></button>
      </div>
      <div class="card-body">
        <!-- 訂單摘要 -->
        <div class="small mb-2">
          <b>{{ order.time || '' }} {{ order.passenger || '—' }}</b>
          <span class="text-muted">·{{ order.fleet || '未標車行' }}</span>
          <span v-if="order.welfare" class="badge bg-warning text-dark ms-1">福</span>
          <div class="text-muted" style="font-size:.78rem">{{ order.pickup }} → {{ order.dropoff }}</div>
        </div>

        <!-- 切換車隊(候選範圍)-->
        <div class="btn-group btn-group-sm w-100 mb-2" role="group">
          <button type="button" class="btn" :class="scope === 'own' ? 'btn-primary' : 'btn-outline-primary'"
                  @click="scope = 'own'">本車行 / 同區</button>
          <button type="button" class="btn" :class="scope === 'company' ? 'btn-primary' : 'btn-outline-primary'"
                  @click="scope = 'company'">全公司(含他隊支援)</button>
        </div>

        <div v-if="error" class="alert alert-danger py-1 px-2 small">{{ error }}</div>
        <div v-if="loading" class="text-center text-muted py-3 small">
          <span class="spinner-border spinner-border-sm me-1"></span>計算插入成本中…
        </div>

        <template v-else-if="data">
          <div v-if="data.error" class="alert alert-warning py-1 px-2 small">{{ data.error }}</div>
          <template v-else>
            <div class="small text-muted mb-1">
              候選 {{ data.candidate_count }} 台 · 直達約 {{ data.direct_min ?? '—' }} 分
              <span v-if="scope === 'own'">（本車行不足時可切「全公司」找支援車）</span>
            </div>
            <div v-if="!allowAssign" class="alert alert-secondary py-1 px-2 small mb-1">
              🔎 唯讀建議：此為歷史/已完成單,僅供評估「是否真無法派遣」;實際指派請於營運日到派遣看板操作。
            </div>
            <div class="table-responsive" style="max-height:46vh;overflow:auto">
              <table class="table table-sm table-hover align-middle mb-0 small">
                <thead class="table-light" style="position:sticky;top:0"><tr>
                  <th>車輛 / 司機</th><th class="text-end">+車程</th><th>現況</th><th></th>
                </tr></thead>
                <tbody>
                  <tr v-for="c in data.candidates" :key="c.vehicle_id" :class="{ 'table-light text-muted': !c.feasible }">
                    <td>
                      <b>{{ c.plate }}</b>
                      <span v-if="c.is_own" class="badge bg-info text-dark ms-1">本車行</span>
                      <span v-else class="badge bg-secondary ms-1">支援·{{ c.fleet || '?' }}</span>
                      <div class="text-muted" style="font-size:.72rem">
                        {{ c.driver || '—' }}<span v-if="c.type === 'welfare'"> · 福祉車</span>
                      </div>
                    </td>
                    <td class="text-end text-nowrap">+{{ c.added_min }} 分
                      <span v-if="c.pooled" class="badge bg-light text-dark" title="與現有趟共乘">併</span>
                    </td>
                    <td class="text-nowrap">
                      {{ c.trip_count }} 趟
                      <span v-if="c.conflict" class="badge bg-danger" title="時間可能衝突">衝突</span>
                      <span v-if="!c.feasible" class="text-danger d-block" style="font-size:.7rem">{{ c.reason }}</span>
                    </td>
                    <td>
                      <button v-if="allowAssign" class="btn btn-sm" :class="c.feasible ? 'btn-success' : 'btn-outline-danger'"
                              :disabled="assigning === c.vehicle_id" @click="adopt(c)">
                        <span v-if="assigning === c.vehicle_id" class="spinner-border spinner-border-sm"></span>
                        <span v-else>採用</span>
                      </button>
                      <span v-else class="text-muted small">—</span>
                    </td>
                  </tr>
                  <tr v-if="!data.candidates.length"><td colspan="4" class="text-center text-muted py-3">
                    此範圍無候選車，請切換到「全公司」。</td></tr>
                </tbody>
              </table>
            </div>
          </template>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sv-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, .4);
  display: flex; align-items: center; justify-content: center; z-index: 1080; padding: 1rem;
}
.sv-modal { width: 100%; max-width: 560px; max-height: 88vh; overflow: auto; }
</style>
