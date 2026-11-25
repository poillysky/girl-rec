// ============================================================
// 通用格式化工具：时间、大小、时长
// ============================================================

/** 字节 → 人类可读（B/KB/MB/GB/TB） */
export function fmtSize(bytes) {
  if (bytes == null || bytes === 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`
}

/** 秒 → HH:MM:SS 或 MM:SS */
export function fmtDur(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}时${String(m).padStart(2, '0')}分${String(s).padStart(2, '0')}秒`
  if (m > 0) return `${m}分${String(s).padStart(2, '0')}秒`
  return `${s}秒`
}

/** 秒 → 计时器风格 HH:MM:SS（直播中进度用） */
export function fmtClock(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return [h, m, s].map(n => String(n).padStart(2, '0')).join(':')
}

/** ISO 时间 → 本地展示（YYYY-MM-DD HH:mm） */
export function fmtTime(iso, withSeconds = false) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return String(iso)
    const p = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}${withSeconds ? ':' + p(d.getSeconds()) : ''}`
  } catch { return String(iso) }
}

/** 相对时间：刚刚 / n分钟前 / n小时前 / 日期 */
export function fmtAgo(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return fmtTime(iso)
}

/** 文件名 → 尾段（跨平台分隔符） */
export function basename(p) {
  return (p || '').split('/').pop().split('\\').pop()
}

/** 秒级时长 → 百分比（相对 1 小时参考，封顶 100） */
export function pctOfHour(seconds, totalSeconds = 0) {
  if (totalSeconds > 0) return Math.min(100, (seconds / totalSeconds) * 100)
  return Math.min(100, (seconds / 3600) * 100)
}

/** kbps 数字 → 可读码率 */
export function fmtBitrate(kbps) {
  if (kbps == null || kbps == null || kbps === 0) return '—'
  if (kbps >= 1000) return `${(kbps / 1000).toFixed(1)} Mbps`
  return `${Math.round(kbps)} kbps`
}

export default { fmtSize, fmtDur, fmtClock, fmtTime, fmtAgo, basename, pctOfHour, fmtBitrate }