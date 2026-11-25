<template>
  <div class="pp" role="group" :aria-label="ariaLabel || '平台多选'">
    <!-- 已选标签 -->
    <div class="pp-chips">
      <button v-for="p in selected" :key="p" type="button" class="pp-chip"
              :aria-label="`移除 ${p}`" @click="remove(p)">
        <span>{{ p }}</span>
        <X :size="12" :stroke-width="2.5" />
      </button>
      <span v-if="!selected.length" class="pp-empty">未选择（全部直连，不走代理）</span>
    </div>
    <!-- 添加：搜索 + 建议标签 -->
    <div class="pp-add">
      <input v-model="q" class="input pp-input" type="text"
             :aria-label="'添加平台'" placeholder="搜索或输入平台名，回车添加"
             @keydown.enter.prevent="addFromInput" @keydown.,.prevent="addFromInput" />
      <button type="button" class="btn sm" @click="addFromInput" :disabled="!q.trim()">
        <Plus :size="13" :stroke-width="2" /> 添加
      </button>
    </div>
    <!-- 常见平台建议 -->
    <div class="pp-suggest">
      <button v-for="p in suggestions" :key="p" type="button"
              class="pp-tag" :class="{ on: selected.includes(p) }"
              @click="toggle(p)">{{ p }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { X, Plus } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: String, default: '' },
  ariaLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

// 常见海外/需代理平台（原版默认名单 + 常用）
const COMMON = [
  'tiktok', 'sooplive', 'pandalive', 'winktv', 'flextv', 'popkontv',
  'twitch', 'liveme', 'showroom', 'chzzk', 'youtube', 'shopee', 'shp', 'faceit',
]

const q = ref('')

// 逗号分隔字符串 ⇄ 数组（去空去重保序）
const selected = computed(() => {
  const seen = new Set()
  const out = []
  for (const raw of (props.modelValue || '').split(/[,，]/)) {
    const v = raw.trim()
    if (v && !seen.has(v)) { seen.add(v); out.push(v) }
  }
  return out
})

function commit(list) {
  emit('update:modelValue', list.join(', '))
}
function add(p) {
  const v = (p || '').trim()
  if (!v) return
  const list = selected.value.slice()
  // 支持一次粘贴多个逗号分隔
  for (const item of v.split(/[,，]/)) {
    const x = item.trim()
    if (x && !list.includes(x)) list.push(x)
  }
  commit(list)
}
function remove(p) { commit(selected.value.filter(x => x !== p)) }
function toggle(p) { selected.value.includes(p) ? remove(p) : add(p) }
function addFromInput() { if (q.value.trim()) { add(q.value); q.value = '' } }

// 建议：常见平台中未选中的（搜索时过滤）
const suggestions = computed(() => {
  const kw = q.value.trim().toLowerCase()
  return COMMON.filter(p => !selected.value.includes(p) && (!kw || p.includes(kw)))
})
</script>

<style scoped>
.pp { display: flex; flex-direction: column; gap: 8px; }
.pp-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-height: 24px; }
.pp-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 6px; cursor: pointer;
  background: var(--accent-soft); color: var(--accent);
  border: 1px solid transparent; font-size: 12px; font-weight: 500;
}
.pp-chip:hover { border-color: var(--accent); }
.pp-empty { font-size: 12px; color: var(--dim); }
.pp-add { display: flex; gap: 8px; align-items: center; }
.pp-input { height: 30px; font-size: 12.5px; flex: 1; max-width: 360px; }
.pp-suggest { display: flex; flex-wrap: wrap; gap: 6px; }
.pp-tag {
  padding: 3px 9px; border-radius: 6px; cursor: pointer; font-size: 11.5px;
  background: var(--panel-2); color: var(--dim); border: 1px solid var(--border-soft);
  transition: color 0.12s, border-color 0.12s;
}
.pp-tag:hover { color: var(--text); border-color: var(--accent); }
.pp-tag.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
</style>
