<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>平台管理</h2>
        <p class="sub">每个平台单独配置 · 代理 / 默认画质 / 启用 / Cookie · 修改即时生效</p>
      </div>
      <div class="actions">
        <span class="tag gray">共 {{ list.length }} 个平台</span>
      </div>
    </div>

    <!-- 搜索 + 过滤 -->
    <div class="filter-bar">
      <input v-model.trim="kw" class="input" style="width:260px" placeholder="搜索平台 / 域名" />
      <Dropdown v-model="proxyFilter" :options="proxyFilterOpts" width="150px" />
      <div class="grow"></div>
      <span class="hint">点「配置」打开该平台参数</span>
    </div>

    <!-- 平台卡片列表 -->
    <div class="plat-grid">
      <div v-for="p in filtered" :key="p.name" class="plat-card">
        <div class="plat-top">
          <span class="plat-name">{{ p.name }}</span>
          <span class="plat-tags">
            <span v-if="proxyOn(p)" class="mini-tag proxy">代理</span>
            <span v-if="p.only_audio" class="mini-tag">音频</span>
            <span v-if="p.only_flv" class="mini-tag">FLV</span>
            <span v-if="p.support_danmu" class="mini-tag">弹幕</span>
          </span>
        </div>
        <div class="plat-domains">{{ p.domains.join(' · ') || '自定义/手动添加' }}</div>
        <div class="plat-foot">
          <span class="plat-summary">画质 {{ paramVal(p, '默认画质') }} · {{ paramVal(p, '录制启用') === '是' ? '录制开' : '录制关' }}</span>
          <button class="btn sm" @click="openCfg(p)"><Settings2 :size="13" :stroke-width="2" /> 配置</button>
        </div>
      </div>
    </div>

    <!-- 平台配置弹窗 -->
    <div v-if="cur" class="modal-mask" @click.self="closeCfg">
      <div class="modal plat-modal">
        <div class="modal-head">
          <h3><Blocks :size="16" :stroke-width="2" style="margin-right:6px" />{{ cur.name }}</h3>
          <button class="x" @click="closeCfg" aria-label="关闭"><X :size="16" :stroke-width="2" /></button>
        </div>
        <div class="modal-body">
          <div class="plat-meta mono">{{ cur.domains.join('  ') || '无固定域名（自定义流）' }}</div>
          <div class="cfg-grid">
            <div v-for="d in cur.params" :key="d.key" class="cfg-row">
              <div class="cfg-label-cell">
                <span class="cfg-label">{{ d.label }}</span>
              </div>
              <div class="cfg-input-cell">
                <!-- 布尔 -->
                <button v-if="d.type === 'bool'" role="switch" :aria-checked="draft(d) === '是'"
                        :class="['switch', 'switch-right', draft(d) === '是' ? 'on' : '']"
                        :aria-label="d.label"
                        @click="setDraft(d, draft(d) === '是' ? '否' : '是')"></button>
                <!-- 下拉 -->
                <Dropdown v-else-if="d.type === 'select'" :model-value="draft(d)"
                          :options="d.options.map(o => ({ label: o, value: o }))"
                          :aria-label="d.label" @update:model-value="v => setDraft(d, v)" />
                <!-- 文本/敏感 -->
                <input v-else :value="draft(d)" class="input mono cell-input"
                       :type="d.secret ? 'password' : 'text'"
                       :aria-label="d.label" :placeholder="d.secret ? '（留空用内置）' : ''"
                       @input="e => setDraft(d, e.target.value)" />
              </div>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="closeCfg">取消</button>
          <button class="btn primary" :disabled="!dirty" @click="saveCfg">
            <Save :size="13" :stroke-width="2" /> {{ dirty ? '保存' : '已保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '../api'
import { toast } from '../utils/toast'
import { Settings2, Blocks, X, Save } from 'lucide-vue-next'
import Dropdown from '../components/Dropdown.vue'

const list = ref([])
const kw = ref('')
const proxyFilter = ref('全部')
const proxyFilterOpts = [
  { label: '全部平台', value: '全部' },
  { label: '走代理', value: 'proxy' },
  { label: '直连', value: 'direct' },
]

const cur = ref(null)          // 当前弹窗平台
const edits = reactive({})     // `${platform}::${key}` -> 编辑值
const orig = reactive({})      // 原始值快照

function skey(p, k) { return `${p}::${k}` }

function paramVal(p, key) {
  return p.params.find(x => x.key === key)?.value ?? ''
}
function proxyOn(p) {
  const v = paramVal(p, '启用代理')
  return v === '是'
}

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(p => {
    if (k && !(p.name.toLowerCase().includes(k) || p.domains.some(d => d.toLowerCase().includes(k)))) return false
    if (proxyFilter.value === 'proxy' && !proxyOn(p)) return false
    if (proxyFilter.value === 'direct' && proxyOn(p)) return false
    return true
  })
})

function openCfg(p) {
  cur.value = p
  for (const d of p.params) {
    edits[skey(p.name, d.key)] = d.value
    orig[skey(p.name, d.key)] = d.value
  }
}
function closeCfg() { cur.value = null }
function draft(d) { return edits[skey(cur.value.name, d.key)] ?? '' }
function setDraft(d, v) { edits[skey(cur.value.name, d.key)] = v }

const dirty = computed(() => {
  if (!cur.value) return false
  return cur.value.params.some(d => (edits[skey(cur.value.name, d.key)] ?? '') !== (orig[skey(cur.value.name, d.key)] ?? ''))
})

async function saveCfg() {
  const p = cur.value
  const changed = p.params.filter(d => (edits[skey(p.name, d.key)] ?? '') !== (orig[skey(p.name, d.key)] ?? ''))
  if (!changed.length) { cur.value = null; return }
  try {
    for (const d of changed) {
      await api.setPlatformConfig(p.name, d.key, edits[skey(p.name, d.key)] ?? '')
      d.value = edits[skey(p.name, d.key)] ?? ''    // 同步到列表数据
      orig[skey(p.name, d.key)] = d.value
    }
    toast.ok(`已保存 ${p.name} 配置`)
    cur.value = null
  } catch (e) {
    toast.err(e.message || '保存失败')
  }
}

async function load() {
  try { list.value = await api.listPlatforms() }
  catch (e) { toast.err(e.message || '加载平台失败') }
}
onMounted(load)
</script>

<style scoped>
.filter-bar { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; }
.grow { flex: 1; }
.hint { font-size: 12px; color: var(--dim); }

.plat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.plat-card {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 14px 16px; display: flex; flex-direction: column; gap: 8px;
  transition: border-color .15s;
}
.plat-card:hover { border-color: var(--accent); }
.plat-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.plat-name { font-size: 14px; font-weight: 600; }
.plat-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.mini-tag { font-size: 10px; padding: 1px 6px; border-radius: 5px; background: var(--panel-2); color: var(--dim); }
.mini-tag.proxy { background: var(--accent-soft); color: var(--accent); }
.plat-domains { font-size: 11.5px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.plat-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 2px; }
.plat-summary { font-size: 11.5px; color: var(--dim); }

.plat-modal { width: 640px; max-width: 92vw; max-height: 84vh; display: flex; flex-direction: column; }
.plat-modal .modal-body { flex: 1; overflow-y: auto; }
.plat-meta { font-size: 11.5px; color: var(--dim); padding: 2px 2px 12px; word-break: break-all; }
.cfg-grid { display: flex; flex-direction: column; }
.cfg-row { display: flex; gap: 16px; padding: 12px 2px; border-bottom: 1px solid var(--border-soft); align-items: flex-start; }
.cfg-row:last-child { border-bottom: none; }
.cfg-label-cell { width: 190px; flex-shrink: 0; padding-top: 4px; }
.cfg-input-cell { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-end; }
.cfg-input-cell .switch-right { margin-left: auto; display: block; }
.cfg-label { font-weight: 500; color: var(--text); font-size: 13px; }
.cell-input { width: 100%; height: 32px; padding: 0 10px; font-size: 12.5px; box-sizing: border-box; }
</style>
