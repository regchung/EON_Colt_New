import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '../views/Dashboard.vue'
import Orders from '../views/Orders.vue'
import Vehicles from '../views/Vehicles.vue'
import Drivers from '../views/Drivers.vue'
import Addresses from '../views/Addresses.vue'
import RouteMap from '../views/RouteMap.vue'
import Login from '../views/Login.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { title: '儀表板' } },
  { path: '/orders', name: 'orders', component: Orders, meta: { title: '訂單管理' } },
  { path: '/vehicles', name: 'vehicles', component: Vehicles, meta: { title: '車輛管理' } },
  { path: '/drivers', name: 'drivers', component: Drivers, meta: { title: '司機管理' } },
  { path: '/addresses', name: 'addresses', component: Addresses, meta: { title: '地址簿' } },
  { path: '/map', name: 'map', component: RouteMap, meta: { title: '路線地圖' } },
  { path: '/login', name: 'login', component: Login, meta: { public: true, layout: false } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守衛:未登入只能進公開頁
router.beforeEach((to) => {
  const authed = !!localStorage.getItem('token')
  if (!to.meta.public && !authed) return { name: 'login' }
  if (to.name === 'login' && authed) return { path: '/' }
  return true
})

export default router
