import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '../views/Dashboard.vue'
import Orders from '../views/Orders.vue'
import Vehicles from '../views/Vehicles.vue'
import Drivers from '../views/Drivers.vue'
import Addresses from '../views/Addresses.vue'
import RouteMap from '../views/RouteMap.vue'
import Reports from '../views/Reports.vue'
import Comparison from '../views/Comparison.vue'
import PoolSuggest from '../views/PoolSuggest.vue'
import Users from '../views/Users.vue'
import Login from '../views/Login.vue'
import DriverRoute from '../views/DriverRoute.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { title: '儀表板' } },
  { path: '/orders', name: 'orders', component: Orders, meta: { title: '訂單管理' } },
  { path: '/vehicles', name: 'vehicles', component: Vehicles, meta: { title: '車輛管理' } },
  { path: '/drivers', name: 'drivers', component: Drivers, meta: { title: '司機管理' } },
  { path: '/addresses', name: 'addresses', component: Addresses, meta: { title: '地址簿' } },
  { path: '/map', name: 'map', component: RouteMap, meta: { title: '路線地圖' } },
  { path: '/reports', name: 'reports', component: Reports, meta: { title: '報表' } },
  { path: '/comparison', name: 'comparison', component: Comparison, meta: { title: '人工 vs 自動' } },
  { path: '/pool-suggest', name: 'pool-suggest', component: PoolSuggest, meta: { title: '共乘建議' } },
  { path: '/users', name: 'users', component: Users, meta: { title: '使用者管理', roles: ['admin'] } },
  { path: '/driver-route', name: 'driver-route', component: DriverRoute, meta: { title: '我的路單', roles: ['driver'] } },
  { path: '/login', name: 'login', component: Login, meta: { public: true, layout: false } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) return { name: 'login' }
  if (to.name === 'login' && token) return { path: '/' }
  return true
})

export default router
