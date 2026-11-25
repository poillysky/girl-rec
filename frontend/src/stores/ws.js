import { defineStore } from 'pinia'
import { ref } from 'vue'

// WebSocket 事件中心：连接后端 /ws/events，接收事件广播并分发给各页面订阅者
export const useWsStore = defineStore('ws', () => {
  const connected = ref(false)
  const lastEvent = ref(null)       // 最近事件（含 session_update 实时进度）
  const listeners = new Set()       // 订阅者集合

  let ws = null
  let retryTimer = null
  let manualClose = false

  function connect() {
    manualClose = false
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${location.host}/ws/events`
    ws = new WebSocket(url)

    ws.onopen = () => { connected.value = true }
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data)
        lastEvent.value = evt
        listeners.forEach((fn) => { try { fn(evt) } catch {} })
      } catch { /* 忽略坏包 */ }
    }
    ws.onclose = () => {
      connected.value = false
      if (!manualClose) retryTimer = setTimeout(connect, 3000)
    }
    ws.onerror = () => { try { ws.close() } catch {} }
  }

  function close() {
    manualClose = true
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
    if (ws) { try { ws.close() } catch {} ws = null }
    connected.value = false
  }

  function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) }

  return { connected, lastEvent, connect, close, subscribe }
})