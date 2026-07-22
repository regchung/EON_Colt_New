<script setup>
import { computed } from 'vue'

const props = defineProps({
  total: { type: Number, required: true },
  page: { type: Number, required: true },
  pageSize: { type: Number, default: 50 },
})
const emit = defineEmits(['update:page'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const from = computed(() => Math.min((props.page - 1) * props.pageSize + 1, props.total))
const to = computed(() => Math.min(props.page * props.pageSize, props.total))

// 顯示的頁碼（最多顯示 7 個按鈕）
const pages = computed(() => {
  const tp = totalPages.value
  const p = props.page
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  const arr = []
  arr.push(1)
  if (p > 4) arr.push('...')
  for (let i = Math.max(2, p - 2); i <= Math.min(tp - 1, p + 2); i++) arr.push(i)
  if (p < tp - 3) arr.push('...')
  arr.push(tp)
  return arr
})

function go(p) {
  if (p >= 1 && p <= totalPages.value) emit('update:page', p)
}
</script>

<template>
  <div v-if="total > 0" class="d-flex align-items-center justify-content-between flex-wrap gap-2 mt-2">
    <small class="text-muted">顯示 {{ from }}–{{ to }}，共 {{ total }} 筆</small>
    <nav v-if="totalPages > 1">
      <ul class="pagination pagination-sm mb-0">
        <li class="page-item" :class="{ disabled: page === 1 }">
          <button class="page-link" @click="go(page - 1)">«</button>
        </li>
        <li v-for="p in pages" :key="p"
            class="page-item"
            :class="{ active: p === page, disabled: p === '...' }">
          <button class="page-link" @click="p !== '...' && go(p)">{{ p }}</button>
        </li>
        <li class="page-item" :class="{ disabled: page === totalPages }">
          <button class="page-link" @click="go(page + 1)">»</button>
        </li>
      </ul>
    </nav>
  </div>
</template>
