<script setup>
import { onMounted, ref } from 'vue'
import client from '../api/client'
import SuggestVehicle from '../components/SuggestVehicle.vue'

// 指派建議面板(未派單:哪台車可行 / 是否跨車行支援;done 日唯讀,營運中單可立即指派)
const suggestOrder = ref(null)
const suggestAllowAssign = ref(false)
function openSuggest(i) {
  suggestOrder.value = {
    id: i.order_id, fleet: i.fleet, passenger: i.passenger,
    pickup: i.pickup, dropoff: i.dropoff, welfare: i.welfare, time: i.pickup_time,
  }
  suggestAllowAssign.value = ['imported', 'scheduled'].includes(i.order_status)
}
async function onSuggestAssigned() {
  suggestOrder.value = null
  await selectDate(sel.value)
}

const fleet = ref('')
const dates = ref([])
const sel = ref('')          // 選定日期
const list = ref([])
const detail = ref(null)     // 選定單筆明細
const cats = ref([])
const loadingList = ref(false)
const error = ref('')
const toast = ref('')

const fb = ref({ category: '', note: '' })
const saving = ref(false)

// 改善建議(#51 學習閉環)
const insights = ref(null)
const insLoading = ref(false)
async function loadInsights(ai) {
  insLoading.value = true
  try {
    const { data } = await client.get('/dispatch/unassigned/insights', {
      params: { ai, ...(fleet.value ? { fleet: fleet.value } : {}) }, timeout: 90000,
    })
    insights.value = data
  } catch (e) { error.value = e.response?.data?.detail || '產生建議失敗' } finally { insLoading.value = false }
}

function flash(m) { toast.value = m; setTimeout(() => { toast.value = '' }, 3000) }

async function loadCats() {
  const { data } = await client.get('/dispatch/unassigned/feedback-categories')
  cats.value = data.categories
}
async function loadDates() {
  const { data } = await client.get('/dispatch/unassigned/dates', {
    params: fleet.value ? { fleet: fleet.value } : {},
  })
  dates.value = data
  if (data.length && !data.find((d) => d.service_date === sel.value)) {
    selectDate(data[0].service_date)
  }
}
async function selectDate(d) {
  sel.value = d
  detail.value = null
  loadingList.value = true
  try {
    const { data } = await client.get('/dispatch/unassigned', {
      params: { service_date: d, ...(fleet.value ? { fleet: fleet.value } : {}) },
    })
    list.value = data.items
  } finally {
    loadingList.value = false
  }
}
async function openDetail(id) {
  const { data } = await client.get(`/dispatch/unassigned/${id}`)
  detail.value = data
  fb.value = { category: data.feedback.category || '', note: data.feedback.note || '' }
}
async function submitFeedback() {
  if (!fb.value.category) { error.value = '請選擇因素類別'; return }
  saving.value = true; error.value = ''
  try {
    await client.post(`/dispatch/unassigned/${detail.value.id}/feedback`, {
      category: fb.value.category, note: fb.value.note || null,
    })
    flash('已記錄行控回饋,感謝協助系統學習')
    await openDetail(detail.value.id)
    await selectDate(sel.value)
    await loadDates()
  } catch (e) {
    error.value = e.response?.data?.detail || '送出失敗'
  } finally {
    saving.value = false
  }
}

async function onFleetChange() { await loadDates() }

onMounted(async () => { await loadCats(); await loadDates() })
</script>

<template>
  <p class="text-muted small">
    系統無法排入的訂單依日期歸類。點日期看當天未派清單 → 點訂單看「系統為何無法派遣」與「人工當時用哪台車」,
    並請行控填入實際因素,協助系統學習改善。
  </p>

  <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
    <!-- 車行篩選隱藏（單一車行大豐） -->
    <span v-if="toast" class="badge bg-success ms-2">{{ toast }}</span>
  </div>
  <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>

  <!-- 改善建議(學習閉環)-->
  <div class="card shadow-sm mb-3 border-primary">
    <div class="card-header bg-primary-subtle d-flex flex-wrap justify-content-between align-items-center gap-2 py-2">
      <span>💡 改善建議(縮小人工 vs 自動差距)</span>
      <span>
        <button class="btn btn-sm btn-outline-primary me-1" :disabled="insLoading" @click="loadInsights(false)">統計建議</button>
        <button class="btn btn-sm btn-primary" :disabled="insLoading" @click="loadInsights(true)">
          <span v-if="insLoading" class="spinner-border spinner-border-sm me-1"></span>AI 診斷
        </button>
      </span>
    </div>
    <div v-if="insights" class="card-body">
      <div class="small text-muted mb-2">未派總數 {{ insights.stats.total }}・行控已回饋 {{ insights.stats.feedback_filled }}{{ insights.fleet ? '・車行 ' + insights.fleet : '' }}</div>
      <div class="row g-3">
        <div class="col-12 col-md-5">
          <div class="fw-semibold small mb-1">建議行動(依影響趟次)</div>
          <ul class="small mb-2">
            <li v-for="(r, i) in insights.recommendations" :key="i">
              <b>{{ r.action }}</b>(約 {{ r.impact }} 趟)
              <span v-if="r.from_feedback" class="badge bg-success">行控回饋</span>
              <div class="text-muted">{{ r.rationale }}</div>
            </li>
            <li v-if="!insights.recommendations.length" class="text-muted">無未派或無可建議項目</li>
          </ul>
        </div>
        <div class="col-12 col-md-7">
          <div v-if="insights.ai_summary" class="border rounded p-2 bg-light small" style="white-space:pre-wrap; max-height:340px; overflow:auto">{{ insights.ai_summary }}</div>
          <div v-else class="text-muted small">按「AI 診斷」產生白話改善方案(需 Claude 金鑰)。</div>
        </div>
      </div>
    </div>
  </div>

  <div class="row g-3">
    <!-- 左:日期清單 -->
    <div class="col-12 col-md-3">
      <div class="card shadow-sm"><div class="card-header py-2 fw-semibold">未派日期</div>
        <div class="list-group list-group-flush" style="max-height:70vh;overflow:auto">
          <button v-for="d in dates" :key="d.service_date" type="button"
                  class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                  :class="{ active: d.service_date === sel }" @click="selectDate(d.service_date)">
            <span>{{ d.service_date }}</span>
            <span>
              <span class="badge bg-danger rounded-pill">{{ d.count }}</span>
              <span v-if="d.feedback_count" class="badge bg-success rounded-pill ms-1" title="已回饋">✓{{ d.feedback_count }}</span>
            </span>
          </button>
          <div v-if="!dates.length" class="text-muted text-center py-4 small">尚無未派資料(需先跑對比批次)</div>
        </div>
      </div>
    </div>

    <!-- 中:當日清單 -->
    <div class="col-12 col-md-5">
      <div class="card shadow-sm"><div class="card-header py-2 fw-semibold">
        {{ sel || '—' }} 未派訂單 <span class="text-muted small">({{ list.length }})</span></div>
        <div class="table-responsive" style="max-height:70vh;overflow:auto">
          <table class="table table-sm table-hover align-middle mb-0 small">
            <thead class="table-light" style="position:sticky;top:0"><tr>
              <th>時間</th><th>路線</th><th>原因</th><th></th></tr></thead>
            <tbody>
              <tr v-for="i in list" :key="i.id" style="cursor:pointer"
                  :class="{ 'table-primary': detail && detail.id === i.id }" @click="openDetail(i.id)">
                <td class="text-nowrap">{{ i.pickup_time || '--' }}
                  <span v-if="i.welfare" class="badge bg-warning text-dark">福</span></td>
                <td><div>{{ i.passenger || '—' }} <span class="text-muted">·{{ i.fleet }}</span></div>
                  <div class="text-muted" style="font-size:.78rem">{{ i.pickup }} → {{ i.dropoff }}</div></td>
                <td><span class="badge bg-secondary">{{ i.reason_label }}</span></td>
                <td class="text-nowrap">
                  <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.72rem"
                          title="指派建議(哪台車可行 / 是否跨車行支援)"
                          @click.stop="openSuggest(i)">💡建議</button>
                  <span v-if="i.has_feedback" class="ms-1" title="已回饋">✓</span>
                </td>
              </tr>
              <tr v-if="!list.length && !loadingList"><td colspan="4" class="text-center text-muted py-4">當日無未派</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 右:明細 + 行控回饋 -->
    <div class="col-12 col-md-4">
      <div v-if="detail" class="card shadow-sm">
        <div class="card-header py-2 fw-semibold">訂單明細與原因</div>
        <div class="card-body">
          <div class="mb-2">
            <span class="badge bg-danger">{{ detail.reason_label }}</span>
            <div class="small text-muted mt-1">{{ detail.reason_detail }}</div>
          </div>
          <table class="table table-sm mb-2"><tbody class="small">
            <tr><th class="text-muted" style="width:6rem">乘客</th><td>{{ detail.order?.passenger || '—' }}
              <span class="text-muted">{{ detail.order?.passenger_phone }}</span></td></tr>
            <tr><th class="text-muted">預約</th><td>{{ detail.order?.pickup_time }}</td></tr>
            <tr><th class="text-muted">上車</th><td>{{ detail.order?.pickup }}</td></tr>
            <tr><th class="text-muted">下車</th><td>{{ detail.order?.dropoff }}</td></tr>
            <tr><th class="text-muted">人數/車種</th><td>{{ detail.order?.pax }} 人 ·
              {{ detail.order?.vehicle_type === 'welfare' ? '福祉車' : '一般車' }}</td></tr>
            <tr class="table-info"><th class="text-muted">人工派遣</th>
              <td><b>{{ detail.human_plate || '(無紀錄)' }}</b> {{ detail.human_driver || '' }}</td></tr>
          </tbody></table>

          <hr class="my-2" />
          <div class="fw-semibold mb-1">🛈 行控回饋(協助系統學習)</div>
          <select v-model="fb.category" class="form-select form-select-sm mb-2">
            <option value="">— 選擇實際因素 —</option>
            <option v-for="c in cats" :key="c" :value="c">{{ c }}</option>
          </select>
          <textarea v-model="fb.note" class="form-control form-control-sm mb-2" rows="2"
                    placeholder="補充說明(選填),例:此客戶其實可改 14:00,或當天有備援車可加班"></textarea>
          <button class="btn btn-sm btn-primary w-100" :disabled="saving" @click="submitFeedback">
            {{ saving ? '送出中…' : (detail.feedback.category ? '更新回饋' : '送出回饋') }}
          </button>
          <div v-if="detail.feedback.by" class="small text-muted mt-1">
            最後由 {{ detail.feedback.by }} 於 {{ (detail.feedback.at || '').slice(0, 16).replace('T', ' ') }} 填寫
          </div>
        </div>
      </div>
      <div v-else class="text-muted text-center py-5 small">← 點選左側訂單查看明細與填寫回饋</div>
    </div>
  </div>

  <SuggestVehicle :order="suggestOrder" :service-date="sel" :allow-assign="suggestAllowAssign"
                  @close="suggestOrder = null" @assigned="onSuggestAssigned" />
</template>
