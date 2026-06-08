import { createResourceStore } from './resource'

export const useOrdersStore = createResourceStore('orders', '/orders')
