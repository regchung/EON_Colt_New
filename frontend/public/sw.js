/* SmartCar service worker — Web Push 推播 */
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = { title: 'SmartCar', body: event.data ? event.data.text() : '' }
  }
  const title = data.title || 'SmartCar 派遣'
  const options = {
    body: data.body || '',
    tag: data.tag || undefined,
    data: { url: data.url || '/' },
    requireInteraction: false,
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (w.url.includes(target) && 'focus' in w) return w.focus()
      }
      if (self.clients.openWindow) return self.clients.openWindow(target)
    }),
  )
})
