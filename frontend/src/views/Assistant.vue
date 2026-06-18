<script setup>
import { nextTick, ref } from 'vue'
import client from '../api/client'

const messages = ref([])   // {role:'user'|'assistant', content, trace?}
const input = ref('')
const loading = ref(false)
const error = ref('')
const boxRef = ref(null)

const SUGGESTIONS = [
  '今天有幾單?還有幾單未排?',
  '列出明天「台北」的需求預測與建議排車數',
  '查一下狀態還是 imported 的訂單',
]

async function scrollDown() {
  await nextTick()
  if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight
}

async function send(text) {
  const q = (text ?? input.value).trim()
  if (!q || loading.value) return
  error.value = ''
  messages.value.push({ role: 'user', content: q })
  input.value = ''
  loading.value = true
  await scrollDown()
  try {
    // 只送純文字往返(role/content),保留多輪上下文
    const payload = { messages: messages.value.map((m) => ({ role: m.role, content: m.content })) }
    const { data } = await client.post('/dispatch/assistant', payload, { timeout: 120000 })
    messages.value.push({ role: 'assistant', content: data.reply || '(無回覆)', trace: data.tool_trace || [] })
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '助理呼叫失敗'
  } finally {
    loading.value = false
    await scrollDown()
  }
}
</script>

<template>
  <p class="text-muted small">
    對話式調度助理:可查詢真實訂單 / 當日出勤 / 營運統計 / 需求預測並給建議(唯讀,不直接執行排班)。
    需設定 <code>ANTHROPIC_API_KEY</code> 方能啟用。
  </p>

  <div ref="boxRef" class="border rounded bg-light p-3 mb-2"
       style="height: 56vh; overflow-y: auto">
    <div v-if="!messages.length" class="text-muted text-center mt-4">
      <div class="mb-3">👋 問我關於今天/某日的營運狀況吧</div>
      <div class="d-flex flex-column align-items-center gap-2">
        <button v-for="s in SUGGESTIONS" :key="s" class="btn btn-sm btn-outline-secondary"
                @click="send(s)">{{ s }}</button>
      </div>
    </div>

    <div v-for="(m, i) in messages" :key="i" class="mb-3">
      <div v-if="m.role === 'user'" class="d-flex justify-content-end">
        <div class="bg-primary text-white rounded px-3 py-2" style="max-width: 80%; white-space: pre-wrap">{{ m.content }}</div>
      </div>
      <div v-else class="d-flex justify-content-start">
        <div class="bg-white border rounded px-3 py-2" style="max-width: 88%; white-space: pre-wrap">
          {{ m.content }}
          <details v-if="m.trace && m.trace.length" class="mt-2 small text-muted">
            <summary>🔍 查了 {{ m.trace.length }} 項資料</summary>
            <ul class="mb-0 ps-3">
              <li v-for="(t, j) in m.trace" :key="j"><code>{{ t.tool }}</code>({{ JSON.stringify(t.input) }})</li>
            </ul>
          </details>
        </div>
      </div>
    </div>

    <div v-if="loading" class="text-muted small"><span class="spinner-border spinner-border-sm me-1"></span>助理思考中…</div>
  </div>

  <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>

  <form class="d-flex gap-2" @submit.prevent="send()">
    <input v-model="input" class="form-control" placeholder="輸入問題,例如:6/20 板橋有哪些未排訂單?"
           :disabled="loading" />
    <button class="btn btn-primary" :disabled="loading || !input.trim()">送出</button>
  </form>
</template>
