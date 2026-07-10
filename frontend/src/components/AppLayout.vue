<script setup>
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { computed, ref, watch } from 'vue'

import { Offcanvas } from 'bootstrap'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const title = computed(() => route.meta.title || 'EON COLT')

// 路由切換後,關閉手機版側欄抽屜(若開著)
watch(
  () => route.path,
  () => {
    const el = document.getElementById('sidebar')
    const inst = el && Offcanvas.getInstance(el)
    if (inst) inst.hide()
  },
)

function logout() {
  auth.logout()
  router.push('/login')
}

const dsp = ['admin', 'dispatcher']
const navGroups = [
  { group: '總覽', items: [
    { to: '/', label: '儀表板', icon: '📊', roles: null },
    { to: '/driver-route', label: '我的路單', icon: '🗒️', roles: ['driver'] },
    { to: '/map', label: '路線地圖', icon: '🗺️', roles: null },
  ] },
  { group: '派遣作業', items: [
    { to: '/dispatch-board', label: '派遣看板', icon: '🧲', roles: dsp },
    { to: '/daily-tasks', label: '車輛任務口卡', icon: '🪪', roles: dsp },
    { to: '/fixed-routes', label: '固定行程', icon: '📌', roles: dsp },
    { to: '/pool-suggest', label: '共乘建議', icon: '🤝', roles: dsp },
    { to: '/unassigned', label: '未派分析', icon: '⚠️', roles: dsp },
  ] },
  { group: '分析報表', items: [
    { to: '/reports', label: '報表', icon: '📈', roles: dsp },
    { to: '/comparison', label: '人工 vs 自動', icon: '🆚', roles: dsp },
    { to: '/vehicle-comparison', label: '逐車對比', icon: '🚐', roles: dsp },
  ] },
  { group: '基礎資料', items: [
    { to: '/orders', label: '訂單管理', icon: '📋', roles: dsp },
    { to: '/vehicles', label: '車輛管理', icon: '🚐', roles: dsp },
    { to: '/drivers', label: '司機管理', icon: '🧑‍✈️', roles: dsp },
    { to: '/daily-roster', label: '每日出勤名冊', icon: '📤', roles: dsp },
    { to: '/roster', label: '班表', icon: '📅', roles: dsp },
    { to: '/addresses', label: '地址簿', icon: '📍', roles: dsp },
  ] },
  { group: '系統', items: [
    { to: '/assistant', label: 'AI 助理', icon: '💬', roles: dsp },
    { to: '/users', label: '使用者管理', icon: '👥', roles: ['admin'] },
    { to: '/settings', label: '參數設定', icon: '⚙️', roles: ['admin'] },
  ] },
]

// 各群組收合狀態(預設全展開);點群組標題切換
const collapsed = ref({})
function toggleGroup(g) { collapsed.value[g] = !collapsed.value[g] }

const nav = computed(() =>
  navGroups
    .map((g) => ({ ...g, items: g.items.filter((i) => !i.roles || i.roles.includes(auth.role)) }))
    .filter((g) => g.items.length),
)
</script>

<template>
  <div>
    <!-- 頂部 navbar(手機顯示漢堡鈕觸發 offcanvas) -->
    <nav class="navbar navbar-dark bg-primary sticky-top">
      <div class="container-fluid">
        <button
          class="navbar-toggler d-lg-none"
          type="button"
          data-bs-toggle="offcanvas"
          data-bs-target="#sidebar"
          aria-controls="sidebar"
        >
          <span class="navbar-toggler-icon"></span>
        </button>
        <span class="navbar-brand mb-0 h1">🚖 EON COLT</span>
        <span class="navbar-text text-white-50 d-none d-sm-inline ms-2">{{ title }}</span>
        <div class="ms-auto d-flex align-items-center gap-2">
          <span class="navbar-text text-white small d-none d-sm-inline">👤 {{ auth.username }}</span>
          <button class="btn btn-sm btn-outline-light" @click="logout">登出</button>
        </div>
      </div>
    </nav>

    <div class="container-fluid">
      <div class="row">
        <!-- 側欄:桌機常駐、手機收成 offcanvas -->
        <nav
          id="sidebar"
          class="offcanvas-lg offcanvas-start col-lg-2 bg-light border-end p-0"
          tabindex="-1"
        >
          <div class="offcanvas-header d-lg-none">
            <h5 class="offcanvas-title">選單</h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="offcanvas"
              data-bs-target="#sidebar"
            ></button>
          </div>
          <div class="offcanvas-body p-0">
            <div class="p-2 w-100">
              <div v-for="g in nav" :key="g.group" class="mb-1">
                <button
                  class="btn btn-sm w-100 d-flex justify-content-between align-items-center px-2 py-1 text-muted fw-semibold text-uppercase"
                  style="font-size:.72rem; letter-spacing:.03em"
                  @click="toggleGroup(g.group)"
                >
                  <span>{{ g.group }}</span>
                  <span>{{ collapsed[g.group] ? '▸' : '▾' }}</span>
                </button>
                <ul v-show="!collapsed[g.group]" class="nav nav-pills flex-column">
                  <li v-for="item in g.items" :key="item.to" class="nav-item">
                    <RouterLink :to="item.to" class="nav-link py-1" active-class="active">
                      <span class="me-2">{{ item.icon }}</span>{{ item.label }}
                    </RouterLink>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </nav>

        <!-- 主內容 -->
        <main class="col-lg-10 py-3 px-3 px-lg-4">
          <h3 class="mb-3">{{ title }}</h3>
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
