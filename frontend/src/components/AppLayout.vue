<script setup>
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { computed, watch } from 'vue'
import { Offcanvas } from 'bootstrap'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const title = computed(() => route.meta.title || 'SmartCar')

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

const nav = [
  { to: '/', label: '儀表板', icon: '📊' },
  { to: '/orders', label: '訂單管理', icon: '📋' },
  { to: '/vehicles', label: '車輛管理', icon: '🚐' },
  { to: '/drivers', label: '司機管理', icon: '🧑‍✈️' },
  { to: '/addresses', label: '地址簿', icon: '📍' },
  { to: '/map', label: '路線地圖', icon: '🗺️' },
]
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
        <span class="navbar-brand mb-0 h1">🚖 SmartCar</span>
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
            <ul class="nav nav-pills flex-column p-2 w-100">
              <li v-for="item in nav" :key="item.to" class="nav-item">
                <RouterLink :to="item.to" class="nav-link" active-class="active">
                  <span class="me-2">{{ item.icon }}</span>{{ item.label }}
                </RouterLink>
              </li>
            </ul>
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
