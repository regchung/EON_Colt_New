import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// 附上 JWT
client.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 401 → 清除登入並導向登入頁
client.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401 && !location.hash.includes('/login')) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      if (location.pathname !== '/login') location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default client
