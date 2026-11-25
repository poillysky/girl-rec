import axios from 'axios'

// 开发用 vite 代理 /api → 127.0.0.1:8000；生产同源（FastAPI 挂载 dist）
const http = axios.create({ baseURL: '/api', timeout: 15000 })

http.interceptors.response.use(
  (r) => r.data,
  (err) => {
    // 响应体里 FastAPI 错误是 detail（可含数组）
    let msg = err.response?.data?.detail || err.message || '请求失败'
    if (Array.isArray(msg)) msg = msg.map(i => i.msg).join('；')
    return Promise.reject(new Error(msg || '请求失败'))
  },
)

export const api = {
  // 系统
  health: () => http.get('/health'),
  stats: () => http.get('/stats'),

  // 直播间
  listRooms: () => http.get('/rooms'),
  createRoom: (data) => http.post('/rooms', data),
  resolveRoom: (data) => http.post('/rooms/resolve', data),
  updateRoom: (id, data) => http.put(`/rooms/${id}`, data),
  deleteRoom: (id) => http.delete(`/rooms/${id}`),

  // 成品库（下载完成的完整 mp4）
  listRecordings: (params) => http.get('/recordings', { params }),
  streamUrl: (id) => `/api/recordings/${id}/stream`,      // 页内播放
  downloadUrl: (id) => `/api/recordings/${id}/download`,  // 下载附件
  deleteProduct: (id, removeFile = true) => http.delete(`/recordings/${id}`, { params: { remove_file: removeFile } }),
  // 缓存库（录制中 ts 分片）
  listCache: () => http.get('/cache'),

  listSessions: () => http.get('/sessions'),

  // 配置
  listConfigs: () => http.get('/configs'),
  setConfig: (key, value) => http.put('/configs', { key, value }),

  // 平台配置（每平台独立参数）
  listPlatforms: () => http.get('/platforms'),
  setPlatformConfig: (platform, key, value) => http.put(`/platforms/${encodeURIComponent(platform)}`, { key, value }),
}

export default api