<script setup>
import { onMounted, ref, computed, watch } from 'vue'
import client from '../api/client'
import Pagination from '../components/Pagination.vue'

const points = ref([])
const unresolved = ref([])

// 分頁
const PAGE_SIZE_A = 50
const aPage = ref(1)
const pagedPoints = computed(() => points.value.slice((aPage.value - 1) * PAGE_SIZE_A, aPage.value * PAGE_SIZE_A))
watch(points, () => { aPage.value = 1 })
const loading = ref(false)

const LEVEL = { '1': '門牌', '2': '門牌', '3': '路口', '4': '道路', fuzzy: '模糊', exact: '精確', approx: '路段' }

async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/addresses')
    points.value = data.points
    unresolved.value = data.unresolved_aliases || []
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div class="d-flex justify-content-between align-items-center mb-3">
    <span class="text-muted">共 {{ points.length }} 個門牌（同一門牌的多種寫法歸為別名)</span>
    <button class="btn btn-outline-secondary btn-sm" :disabled="loading" @click="load">重新整理</button>
  </div>

  <div class="alert alert-secondary small">
    地址一經 Map8 解析即存入此地址簿(校正後地址 + 座標)。之後相同或不同寫法的地址
    <strong>先查此表、命中就不再呼叫 Map8</strong>,節省費用並加速。
  </div>

  <div class="table-responsive">
    <table class="table table-striped align-middle">
      <thead>
        <tr>
          <th>#</th><th>校正後地址</th><th>行政區</th><th>精度</th>
          <th>座標</th><th>原始描述(別名)</th><th>來源</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in pagedPoints" :key="p.id">
          <td>{{ p.id }}</td>
          <td class="fw-semibold">{{ p.standardized_address }}</td>
          <td class="small text-nowrap">{{ p.city }}{{ p.town }}</td>
          <td>
            <span class="badge" :class="['1','2','exact'].includes(p.precision) ? 'bg-success' : 'bg-secondary'">
              {{ LEVEL[p.precision] || p.precision }}
            </span>
          </td>
          <td class="small text-nowrap">{{ p.lat?.toFixed(5) }}, {{ p.lng?.toFixed(5) }}</td>
          <td class="small">
            <span v-for="(a, i) in p.aliases" :key="i" class="badge bg-light text-dark border me-1 mb-1">{{ a }}</span>
          </td>
          <td><span class="badge bg-info text-dark">{{ p.source }}</span></td>
        </tr>
        <tr v-if="!points.length">
          <td colspan="7" class="text-center text-muted py-4">尚無地址,先到訂單頁做地理編碼。</td>
        </tr>
      </tbody>
    </table>
    <Pagination :total="points.length" v-model:page="aPage" :page-size="PAGE_SIZE_A" />
  </div>

  <div v-if="unresolved.length" class="alert alert-warning mt-2 small">
    查無座標的地址({{ unresolved.length }}):{{ unresolved.join('、') }}
  </div>
</template>
