// ============================================================
// Toast 消息系统（非侵入式全局提示，替代 alert/console）
// ============================================================
import { reactive } from 'vue'

const toasts = reactive([])
let seq = 0

export { toasts }

function push(type, msg, timeout) {
  const id = ++seq
  toasts.push({ id, type, msg })
  if (timeout) {
    setTimeout(() => dismiss(id), timeout)
  }
}

export function dismiss(id) {
  const i = toasts.findIndex(t => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

export const toast = {
  ok: (msg) => push('ok', msg, 3000),
  err: (msg) => push('err', msg, 5000),
  info: (msg) => push('info', msg, 3000),
  dismiss,
}

export function useToast() {
  return { toasts, toast }
}

export default toast