import { defineStore } from 'pinia'
import client from '../api/client'

// 產生一個通用的 CRUD store(訂單/車輛/司機共用)
export function createResourceStore(name, endpoint) {
  return defineStore(name, {
    state: () => ({
      items: [],
      loading: false,
      error: null,
    }),
    actions: {
      async fetchAll(params = {}) {
        this.loading = true
        this.error = null
        try {
          const { data } = await client.get(endpoint, { params })
          this.items = data
        } catch (e) {
          this.error = e?.response?.data?.detail || e.message
        } finally {
          this.loading = false
        }
      },
      async create(payload) {
        const { data } = await client.post(endpoint, payload)
        this.items.push(data)
        return data
      },
      async update(id, payload) {
        const { data } = await client.put(`${endpoint}/${id}`, payload)
        const i = this.items.findIndex((x) => x.id === id)
        if (i !== -1) this.items[i] = data
        return data
      },
      async remove(id) {
        await client.delete(`${endpoint}/${id}`)
        this.items = this.items.filter((x) => x.id !== id)
      },
    },
  })
}
