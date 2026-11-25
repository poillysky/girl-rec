<script setup>
// 全局 Toast 容器：挂载一个即可全站使用（App.vue）
import { toasts, dismiss } from '../utils/toast'

const icons = { ok: '✅', err: '⚠️', info: 'ℹ️' }
</script>

<template>
  <div class="toast-wrap">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
        <span class="ico">{{ icons[t.type] || 'ℹ️' }}</span>
        <span class="msg">{{ t.msg }}</span>
        <button class="close" @click="dismiss(t.id)">×</button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-wrap { position: fixed; top: 18px; right: 18px; z-index: 300; display: flex; flex-direction: column; gap: 8px; }
.toast {
  display: flex; align-items: flex-start; gap: 10px; min-width: 260px; max-width: min(420px, calc(100vw - 36px));
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; font-size: 13px; box-shadow: var(--shadow-lg);
}
.toast.ok { border-left: 3px solid var(--green); }
.toast.err { border-left: 3px solid var(--red); }
.toast.info { border-left: 3px solid var(--accent); }
.toast .ico { font-size: 15px; line-height: 1.3; }
.toast .msg { flex: 1; word-break: break-all; line-height: 1.45; }
.toast .close { background: none; border: none; color: var(--dim-2); cursor: pointer; font-size: 14px; padding: 0 4px; }
.toast-enter-active, .toast-leave-active { transition: all .22s ease; }
.toast-enter-from { opacity: 0; transform: translateX(24px); }
.toast-leave-to { opacity: 0; transform: translateX(24px); }
</style>