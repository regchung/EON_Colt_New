import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '../views/Dashboard.vue'
import Orders from '../views/Orders.vue'
import Vehicles from '../views/Vehicles.vue'
import Drivers from '../views/Drivers.vue'
import Addresses from '../views/Addresses.vue'
import RouteMap from '../views/RouteMap.vue'
import Reports from '../views/Reports.vue'
import Comparison from '../views/Comparison.vue'
import VehicleComparison from '../views/VehicleComparison.vue'
import PoolSuggest from '../views/PoolSuggest.vue'
import Users from '../views/Users.vue'
import Settings from '../views/Settings.vue'
import Roster from '../views/Roster.vue'
import Assistant from '../views/Assistant.vue'
import DailyTasks from '../views/DailyTasks.vue'
import Unassigned from '../views/Unassigned.vue'
import FixedRoutes from '../views/FixedRoutes.vue'
import DispatchBoard from '../views/DispatchBoard.vue'
import Login from '../views/Login.vue'
import DriverRoute from '../views/DriverRoute.vue'
import DailyRoster from '../views/DailyRoster.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { title: '儀表板' } },
  { path: '/orders', name: 'orders', component: Orders, meta: { title: '訂單管理' } },
  { path: '/vehicles', name: 'vehicles', component: Vehicles, meta: { title: '車輛管理' } },
  { path: '/roster', name: 'roster', component: Roster, meta: { title: '班表', roles: ['admin', 'dispatcher'] } },
  { path: '/drivers', name: 'drivers', component: Drivers, meta: { title: '司機管理' } },
  { path: '/addresses', name: 'addresses', component: Addresses, meta: { title: '地址簿' } },
  { path: '/map', name: 'map', component: RouteMap, meta: { title: '路線地圖' } },
  { path: '/reports', name: 'reports', component: Reports, meta: { title: '報表' } },
  { path: '/comparison', name: 'comparison', component: Comparison, meta: { title: '人工 vs 自動' } },
  { path: '/vehicle-comparison', name: 'vehicle-comparison', component: VehicleComparison, meta: { title: '逐車對比', roles: ['admin', 'dispatcher'] } },
  { path: '/daily-tasks', name: 'daily-tasks', component: DailyTasks, meta: { title: '車輛任務口卡', roles: ['admin', 'dispatcher'] } },
  { path: '/dispatch-board', name: 'dispatch-board', component: DispatchBoard, meta: { title: '派遣看板', roles: ['admin', 'dispatcher'] } },
  { path: '/unassigned', name: 'unassigned', component: Unassigned, meta: { title: '未派分析', roles: ['admin', 'dispatcher'] } },
  { path: '/fixed-routes', name: 'fixed-routes', component: FixedRoutes, meta: { title: '固定行程', roles: ['admin', 'dispatcher'] } },
  { path: '/pool-suggest', name: 'pool-suggest', component: PoolSuggest, meta: { title: '共乘建議' } },
  { path: '/assistant', name: 'assistant', component: Assistant, meta: { title: 'AI 助理', roles: ['admin', 'dispatcher'] } },
  { path: '/users', name: 'users', component: Users, meta: { title: '使用者管理', roles: ['admin'] } },
  { path: '/settings', name: 'settings', component: Settings, meta: { title: '參數設定', roles: ['admin'] } },
  { path: '/driver-route', name: 'driver-route', component: DriverRoute, meta: { title: '我的路單', roles: ['driver'] } },
  { path: '/daily-roster', name: 'daily-roster', component: DailyRoster, meta: { title: '每日出勤名冊', roles: ['admin', 'dispatcher'] } },
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
  // 角色守衛:meta.roles 指定時,非該角色導回首頁
  if (to.meta.roles && !to.meta.roles.includes(localStorage.getItem('role'))) {
    return { path: '/' }
  }
  return true
})

export default router
