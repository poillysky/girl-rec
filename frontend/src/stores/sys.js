// ============================================================
// 全局状态：引擎健康 + WebSocket 实时通道 + 磁盘 / ffmpeg 统计
// 顶栏与总览页共用，避免各页面重复轮询
// ============================================================
import { defineStore } from 'pinia'

export const useSysStore = defineStore('sys', {
  state: () => ({
    health: null,        // {status, rooms, sessions, db}
    stats: null,         // {rooms, sessions, recordings, disk, ffmpeg}
  }),
  actions: {
    async refreshHealth() {
      try {
        const { api } = await import('../api')
        this.health = await api.health()
      } catch { this.health = null }
    },
    async refreshStats() {
      try {
        const { api } = await import('../api')
        this.stats = await api.stats()
      } catch { /* 后端未起时静默 */ }
    },
  },
})