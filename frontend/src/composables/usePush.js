/* 司機端 Web Push 訂閱:註冊 service worker → 取得 VAPID 公鑰 → 訂閱 → 回報後端。 */
import client from '../api/client'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const arr = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i)
  return arr
}

export function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export async function getPushState() {
  if (!pushSupported()) return { supported: false, subscribed: false, permission: 'unsupported' }
  const reg = await navigator.serviceWorker.getRegistration()
  const sub = reg ? await reg.pushManager.getSubscription() : null
  return { supported: true, subscribed: !!sub, permission: Notification.permission }
}

export async function enablePush(driverId = null) {
  if (!pushSupported()) throw new Error('此瀏覽器不支援推播通知')
  const { data: cfg } = await client.get('/config')
  if (!cfg.push_enabled || !cfg.vapid_public_key) {
    throw new Error('伺服器尚未啟用推播(未設定 VAPID 金鑰)')
  }
  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') throw new Error('您未允許通知權限')
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key),
    })
  }
  await client.post('/push/subscribe', { subscription: sub.toJSON(), driver_id: driverId })
  return true
}

export async function disablePush() {
  if (!pushSupported()) return
  const reg = await navigator.serviceWorker.getRegistration()
  if (!reg) return
  const sub = await reg.pushManager.getSubscription()
  if (sub) {
    await client.post('/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {})
    await sub.unsubscribe()
  }
}

export async function sendTestPush(driverId = null) {
  await client.post('/push/test', { driver_id: driverId })
}
