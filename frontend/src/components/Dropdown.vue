<template>
  <div ref="root" class="dd" :style="rootStyle">
    <button ref="btn" type="button" class="dd-btn" :class="{ open }" @click="toggle">
      <span class="dd-label" :class="{ placeholder: !selected }">{{ selected || placeholder }}</span>
      <ChevronDown :size="14" :stroke-width="2" class="dd-caret" :class="{ open }" />
    </button>
    <teleport to="body">
      <transition name="dd-fade">
        <div v-if="open" ref="panel" class="dd-panel" :style="panelStyle">
          <button v-for="opt in options" :key="String(opt.value)" type="button"
                  class="dd-item" :class="{ active: opt.value === modelValue }"
                  @click="choose(opt.value)">
            <span class="dd-item-label">{{ opt.label }}</span>
            <Check v-if="opt.value === modelValue" :size="14" :stroke-width="2.4" class="dd-check" />
          </button>
          <div v-if="!options.length" class="dd-empty">无选项</div>
        </div>
      </transition>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: '' },
  options: { type: Array, default: () => [] },   // [{ label, value }]
  placeholder: { type: String, default: '请选择' },
  width: { type: String, default: '' },   // 留空 = 按内容自适应宽度
})
const emit = defineEmits(['update:modelValue', 'change'])

const root = ref(null)
const btn = ref(null)
const panel = ref(null)
const open = ref(false)
const panelStyle = ref({})
const rootStyle = computed(() => (props.width ? { width: props.width } : null))
const selected = computed(() => {
  const o = props.options.find(x => x.value === props.modelValue)
  return o ? o.label : ''
})

// 面板 fixed 定位到按钮下方：脱离滚动容器裁剪，且不会被弹窗 overflow 截断
function positionPanel() {
  const b = btn.value
  if (!b) return
  const r = b.getBoundingClientRect()
  const maxH = 280
  const spaceBelow = window.innerHeight - r.bottom
  const openUp = spaceBelow < 160 && r.top > spaceBelow
  const style = {
    position: 'fixed',
    left: r.left + 'px',
    // 按钮宽度自适应内容：面板至少与按钮同宽，内容更长时按内容撑开，且不超出视口
    minWidth: r.width + 'px',
    maxWidth: Math.max(120, window.innerWidth - r.left - 12) + 'px',
    zIndex: 2000,
  }
  if (openUp) {
    style.bottom = (window.innerHeight - r.top + 6) + 'px'
    style.maxHeight = Math.min(maxH, r.top - 10) + 'px'
  } else {
    style.top = (r.bottom + 6) + 'px'
    style.maxHeight = Math.min(maxH, spaceBelow - 10) + 'px'
  }
  panelStyle.value = style
}

async function toggle() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    positionPanel()
    window.addEventListener('scroll', positionPanel, true)
    window.addEventListener('resize', positionPanel)
  } else {
    removeListeners()
  }
}
function removeListeners() {
  window.removeEventListener('scroll', positionPanel, true)
  window.removeEventListener('resize', positionPanel)
}
function choose(v) {
  emit('update:modelValue', v)
  emit('change', v)
  open.value = false
  removeListeners()
}
function onDocClick(e) {
  if (open.value && root.value && !root.value.contains(e.target)
      && panel.value && !panel.value.contains(e.target)) {
    open.value = false
    removeListeners()
  }
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onUnmounted(() => {
  document.removeEventListener('mousedown', onDocClick)
  removeListeners()
})
</script>

<style scoped>
.dd { position: relative; display: inline-block; max-width: 100%; }
.dd-btn {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  width: 100%; height: 34px; padding: 0 12px;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text); font-size: 13px; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;
}
.dd-btn:hover { border-color: var(--border-strong, #3a4152); }
.dd-btn.open { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,140,255,0.15); }
.dd-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dd-label.placeholder { color: var(--muted, #6b7280); }
.dd-caret { color: var(--dim); flex: none; transition: transform 0.18s; }
.dd-caret.open { transform: rotate(180deg); }
.dd-panel {
  background: var(--panel-2, #1b1f2b); border: 1px solid var(--border);
  border-radius: 9px; padding: 5px; box-shadow: 0 12px 34px rgba(0,0,0,0.5);
  overflow-y: auto; box-sizing: border-box;
}
.dd-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  width: 100%; padding: 8px 10px; border: none; background: transparent; border-radius: 6px;
  color: var(--text); font-size: 13px; text-align: left; cursor: pointer; transition: background 0.12s;
}
.dd-item:hover { background: rgba(255,255,255,0.06); }
.dd-item.active { color: var(--accent); background: rgba(79,140,255,0.10); }
.dd-item-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dd-check { color: var(--accent); flex: none; }
.dd-empty { padding: 10px; font-size: 12px; color: var(--dim); text-align: center; }
.dd-fade-enter-active, .dd-fade-leave-active { transition: opacity 0.14s, transform 0.14s; }
.dd-fade-enter-from, .dd-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
