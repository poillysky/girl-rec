<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>直播间</h2>
        <p class="sub">管理监控列表 · 添加直播间后自动识别平台并开始探测</p>
      </div>
      <div class="actions">
        <button class="btn primary" @click="openAdd"><Plus :size="15" :stroke-width="2.2" /> 添加直播间</button>
      </div>
    </div>

    <!-- 汇总条 -->
    <div class="summary-bar">
      <span class="sum-item"><b>{{ rooms.length }}</b> 总计</span>
      <span class="sum-item"><b class="ok">{{ enabledCount }}</b> 启用</span>
      <span class="sum-item"><b class="live">{{ liveCount }}</b> 直播中</span>
      <span class="sum-item"><b class="imp">{{ importantCount }}</b> 重要</span>
      <div class="grow"></div>
      <div class="filters">
        <input v-model.trim="kw" class="input" style="width:200px" placeholder="搜索平台 / 主播 / 备注 / URL" />
        <select v-model="platFilter" class="select" style="width:140px">
          <option value="">全部平台</option>
          <option v-for="p in platforms" :key="p" :value="p">{{ p }}</option>
        </select>
      </div>
    </div>

    <!-- 房间列表 -->
    <section class="card">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th class="ta-c" style="width:42px">#</th>
              <th style="width:72px">平台</th>
              <th style="width:88px">在线状态</th>
              <th style="width:92px">录制状态</th>
              <th style="width:120px">主播名字</th>
              <th style="width:120px">ID</th>
              <th class="ta-l" style="width:auto">标题</th>
              <th style="width:64px">画质</th>
              <th class="ta-c" style="width:64px">启用</th>
              <th class="ta-c" style="width:56px">重要</th>
              <th class="ta-c" style="width:92px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in filtered" :key="r.id">
              <td class="ta-c dim num">{{ r.id }}</td>
              <td><span class="tag blue" :class="{ purple: isImportant(r) }">{{ r.platform }}</span></td>
              <td>
                <span :class="['tag', r.is_live ? 'green' : 'gray']">
                  <span v-if="r.is_live" class="dotp"></span>{{ r.is_live ? '直播中' : '未开播' }}
                </span>
              </td>
              <td>
                <span :class="['tag', recStateMeta(r.session_state).cls]">
                  <span v-if="recStateMeta(r.session_state).active" class="dotp"></span>{{ recStateMeta(r.session_state).text }}
                </span>
              </td>
              <td>
                <div class="cell-main">
                  <User :size="13" :stroke-width="2" class="dim" style="margin-right:4px" />
                  <span class="nm ellip">{{ r.anchor_name || r.name || '未知主播' }}</span>
                </div>
              </td>
              <td><span class="mono dim nowrap">{{ roomId(r.url) }}</span></td>
              <td class="ta-l"><span class="cell-title ellip" :title="r.title">{{ r.title || '—' }}</span></td>
              <td><span class="badge">{{ r.quality }}</span></td>
              <td class="ta-c">
                <button :class="['switch', r.enabled ? 'on' : '']" @click="toggleEnabled(r)" :title="r.enabled ? '点击停用' : '点击启用'"></button>
              </td>
              <td class="ta-c">
                <button :class="['switch', r.important ? 'on' : '']" @click="toggleImportant(r)" :title="'重要房间：探测间隔减半'"></button>
              </td>
              <td>
                <div class="actions-row" style="justify-content:center">
                  <button class="btn sm" @click="openEdit(r)" title="编辑"><Pencil :size="13" :stroke-width="2" /></button>
                  <button class="btn sm danger" @click="confirmRemove(r)" title="删除"><Trash2 :size="13" :stroke-width="2" /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!filtered.length" class="empty">
        <div class="big"><component :is="rooms.length ? IcSearch : IcMonitorPlay" :size="34" :stroke-width="1.6" /></div>
        {{ rooms.length ? '没有匹配的房间' : '还没有直播间，点击右上角"添加直播间"开始' }}
      </div>
    </section>

    <!-- ====== 添加/编辑抽屉弹窗 ====== -->
    <div v-if="showModal" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ editing ? '编辑直播间 #' + editing.id : '添加直播间' }}</h3>
          <button class="x" @click="closeModal" aria-label="关闭"><X :size="16" :stroke-width="2" /></button>
        </div>
        <div class="modal-body">
          <div class="col">
            <!-- 第1步：选择平台 -->
            <label class="field">
              <span class="label">平台</span>
              <select v-model="form.platform" class="select" @change="onPlatformChange">
                <option v-for="p in platformOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </label>

            <!-- 第2步：房间ID / 直播间链接 -->
            <label class="field">
              <span class="label">直播间 ID / 链接 <span style="color:var(--red)">*</span></span>
              <div class="row" style="gap:8px">
                <input v-model.trim="form.identifier" class="input grow"
                       :placeholder="form.platform === '抖音' ? '如：335354047186，或直播间链接' : '直播间 ID 或链接'"
                       @keyup.enter="resolve" @input="onIdentifierInput" />
                <button class="btn" :disabled="!form.identifier.trim() || resolveState === 'loading'" @click="resolve" type="button">
                  <Search :size="14" :stroke-width="2" /> 识别
                </button>
              </div>
              <span class="dim" style="font-size:11px" v-if="form.platform === '抖音'">粘贴房间ID或链接后点「识别」，自动填充主播名</span>
            </label>

            <!-- 解析状态/结果 -->
            <div v-if="resolveState === 'loading'" class="resolve-box"><span class="spinner"></span> 正在解析主播…</div>
            <div v-else-if="resolveState === 'ok'" class="resolve-box ok">
              <CheckCircle2 :size="14" :stroke-width="2" />
              <div class="resolve-info">
                <div class="resolve-url mono">{{ resolved.url }}</div>
                <div class="resolve-meta" v-if="resolved.anchor_name">
                  👤 {{ resolved.anchor_name }}<template v-if="resolved.title"> · {{ resolved.title }}</template>
                </div>
              </div>
              <button class="link-btn" @click="resolveState = 'idle'; form.identifier = ''">清除</button>
            </div>
            <div v-else-if="resolveState === 'err'" class="resolve-box err">
              <AlertCircle :size="14" :stroke-width="2" />
              <span>{{ resolveError }}</span>
            </div>

            <div class="row" style="gap:12px">
              <label class="field grow">
                <span class="label">主播名 <span class="dim" style="font-weight:400">（识别后自动填充）</span></span>
                <input v-model.trim="form.name" class="input" placeholder="识别后自动填充" />
              </label>
              <label class="field" style="width:130px">
                <span class="label">画质</span>
                <select v-model="form.quality" class="select">
                  <option v-for="q in qualities" :key="q">{{ q }}</option>
                </select>
              </label>
            </div>
            <div class="row" style="gap:22px; padding-top:4px">
              <label class="row" style="gap:9px; cursor:pointer">
                <button :class="['switch', form.enabled ? 'on' : '']" @click="form.enabled = !form.enabled" type="button"></button>
                <span class="dim">立即启用</span>
              </label>
              <label class="row" style="gap:9px; cursor:pointer">
                <button :class="['switch', form.important ? 'on' : '']" @click="form.important = !form.important" type="button"></button>
                <span class="dim">重要房间（更快探测）</span>
              </label>
            </div>
          </div>
          <p v-if="err" class="mt-3" style="color:var(--red);font-size:12px">{{ err }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="closeModal">取消</button>
          <button class="btn primary" :disabled="busy || resolveState === 'loading'" @click="save">
            {{ busy ? '保存中…' : editing ? '保存修改' : '添加' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="delTarget" class="modal-mask" @click.self="delTarget = null">
      <div class="modal" style="width:360px">
        <div class="modal-head"><h3>删除直播间</h3><button class="x" @click="delTarget = null" aria-label="关闭"><X :size="16" :stroke-width="2" /></button></div>
        <div class="modal-body">
          <p style="font-size:13px;line-height:1.6">
            确定删除 <b style="color:var(--accent-text)">{{ delTarget.name || delTarget.url }}</b> 吗？<br />
            <span class="dim">已录制的历史文件不会被删除。</span>
          </p>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="delTarget = null">取消</button>
          <button class="btn danger" :disabled="busy" @click="doRemove">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { toast } from '../utils/toast'
import { Plus, Pencil, Trash2, X, User, Search, MonitorPlay, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import { fmtTime } from '../utils/format'
import { useWsStore } from '../stores/ws'

const IcSearch = Search
const IcMonitorPlay = MonitorPlay

const ws = useWsStore()
const rooms = ref([])
const platforms = ref([])
const kw = ref('')
const platFilter = ref('')
const qualities = ['原画', '超清', '高清', '标清', '流畅']

// 添加时可选平台（老大：先搞定抖音，一个平台一个平台来）
const platformOptions = ref([
  { value: '抖音', label: '抖音直播' },
  { value: '自定义录制直播', label: '自定义流 (.m3u8/.flv)' },
])

const showModal = ref(false)
const editing = ref(null)       // null=添加
const form = ref({ platform: '抖音', identifier: '', name: '', quality: '原画', enabled: true, important: false })
const resolveState = ref('idle')   // idle | loading | ok | err
const resolved = ref(null)         // {url, platform}
const resolveError = ref('')
const busy = ref(false)
const err = ref('')
const delTarget = ref(null)

const enabledCount = computed(() => rooms.value.filter(r => r.enabled).length)
const liveCount = computed(() => rooms.value.filter(r => r.is_live).length)
const importantCount = computed(() => rooms.value.filter(r => r.important).length)

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return rooms.value.filter(r => {
    if (platFilter.value && r.platform !== platFilter.value) return false
    if (!k) return true
    return [r.platform, r.anchor_name, r.name, r.url].some(v => (v || '').toLowerCase().includes(k))
  })
})

function isImportant(r) { return r.important }
// 录制状态徽标（只管录制相关，探测/闲置与录制无关，统一归为"未录制"）
// 录制中 / 准备中 / 停止中 / 已完成 / 录制异常 / 已停止 / 未录制
const REC_STATE = {
  recording: { text: '录制中', cls: 'red', active: true },
  preparing: { text: '准备中', cls: 'amber', active: true },
  stopping:  { text: '停止中', cls: 'amber', active: true },
  finished:  { text: '已完成', cls: 'green', active: false },
  failed:    { text: '录制异常', cls: 'red',   active: false },
  stopped:   { text: '已停止', cls: 'gray',  active: false },
  // 探测/空闲与录制无关 → 视为未录制
  checking:  { text: '未录制', cls: 'gray', active: false },
  idle:      { text: '未录制', cls: 'gray', active: false },
}
function recStateMeta(state) {
  return REC_STATE[state] || { text: '—', cls: 'gray', active: false }
}
// 从 URL 提取直播间号/ID（取最后一段路径或 host+path 尾）
function roomId(url) {
  if (!url) return ''
  try {
    const u = new URL(url)
    const seg = u.pathname.replace(/\/+$/, '').split('/').pop()
    return seg || u.host
  } catch { return url }
}

async function load() {
  try {
    rooms.value = await api.listRooms()
    platforms.value = [...new Set(rooms.value.map(r => r.platform))].sort()
  } catch (e) { toast.err(e.message) }
}

function openAdd() {
  editing.value = null
  form.value = { platform: '抖音', identifier: '', name: '', quality: '原画', enabled: true, important: false }
  resolveState.value = 'idle'
  resolved.value = null
  resolveError.value = ''
  err.value = ''
  showModal.value = true
  setTimeout(() => { const el = document.querySelector('.modal input'); el && el.focus() }, 60)
}

function openEdit(r) {
  editing.value = r
  form.value = { platform: r.platform, identifier: r.url, name: r.name, quality: r.quality, enabled: r.enabled, important: r.important }
  resolveState.value = 'idle'
  resolved.value = { url: r.url, platform: r.platform }
  resolveError.value = ''
  err.value = ''
  showModal.value = true
}

function closeModal() { showModal.value = false; editing.value = null }

// 平台切换：抖音保持提示，自定义流直接跳过解析
function onPlatformChange() {
  if (form.value.platform === '自定义录制直播') {
    resolveState.value = 'idle'
    resolved.value = null
  } else {
    // 切回抖音：输入变了自动重新解析
    if (form.value.identifier) resolve()
  }
}

function onIdentifierInput() {
  // 输入变化即回到待确认状态
  if (resolveState.value !== 'idle') {
    resolveState.value = 'idle'
    resolved.value = null
  }
}

// 手动解析（确认按钮/回车触发）
let resolveTimer = null
async function resolve() {
  const id = form.value.identifier.trim()
  if (!id) { resolveState.value = 'idle'; resolved.value = null; return }
  if (form.value.platform === '自定义录制直播') {
    // 自定义流：判定是否 .m3u8/.flv 直链
    if (/\.(m3u8|flv)(\?|$)/i.test(id)) {
      resolved.value = { url: id, platform: '自定义录制直播' }
      resolveState.value = 'ok'
    } else {
      resolveState.value = 'err'
      resolveError.value = '自定义流需为 .m3u8 或 .flv 直链'
    }
    return
  }
  clearTimeout(resolveTimer)
  resolveTimer = setTimeout(async () => {
    resolveState.value = 'loading'
    try {
      const r = await api.resolveRoom({ platform: form.value.platform, identifier: id })
      if (r.ok) {
        resolved.value = r
        resolveState.value = 'ok'
        // 主播名由识别自动填充（唯一来源，覆盖写入）
        if (r.info?.anchor_name) {
          form.value.name = r.info.anchor_name
        }
      } else {
        resolveState.value = 'err'
        resolveError.value = r.error || '未能解析该主播'
      }
    } catch (e) {
      resolveState.value = 'err'
      resolveError.value = e.message
    }
  }, 300)
}

async function save() {
  if (!form.value.identifier.trim()) { err.value = '请输入主播名 / ID / 链接'; return }
  // 保存前确保有解析结果（无结果则先解析一次）
  if (!resolved.value || resolved.value.url !== form.value.identifier.trim()) {
    await resolve()
    if (resolveState.value !== 'ok') return
  }
  busy.value = true; err.value = ''
  const url = resolved.value.url
  try {
    if (editing.value) {
      await api.updateRoom(editing.value.id, { ...form.value, identifier: url, url })
      toast.ok('已保存修改')
    } else {
      await api.createRoom({ ...form.value, identifier: url, url })
      toast.ok('直播间已添加，开始探测')
    }
    closeModal()
    await load()
  } catch (e) { err.value = e.message } finally { busy.value = false }
}

async function toggleEnabled(r) {
  try {
    await api.updateRoom(r.id, { ...r, enabled: !r.enabled })
    r.enabled = !r.enabled
    toast.info(r.enabled ? `已启用 ${r.name || r.url}` : `已停用 ${r.name || r.url}`)
  } catch (e) { toast.err(e.message) }
}

async function toggleImportant(r) {
  try {
    await api.updateRoom(r.id, { ...r, important: !r.important })
    r.important = !r.important
    toast.info(r.important ? '已设为重要房间（探测间隔减半）' : '已取消重要房间')
  } catch (e) { toast.err(e.message) }
}

function confirmRemove(r) { delTarget.value = r }

async function doRemove() {
  busy.value = true
  try {
    await api.deleteRoom(delTarget.value.id)
    toast.ok('已删除')
    delTarget.value = null
    await load()
  } catch (e) { toast.err(e.message) } finally { busy.value = false }
}

// ---- WebSocket 实时更新：状态/在线/标题随事件就地刷新，无需手动刷新列表 ----
function applyEventToRoom(rid, patch) {
  const r = rooms.value.find(x => x.id === rid)
  if (!r) return
  Object.assign(r, patch)
}

function onWsEvent(evt) {
  const t = evt.type
  const d = evt.data || {}          // 后端广播格式：{ type, data: {...} }
  const rid = d.room_id
  if (!rid) return
  if (t === 'session_update') {
    // 录制状态实时更新（checking/preparing/recording/finished/stopped/failed…）
    const patch = { session_state: d.state }
    if (d.anchor) patch.anchor_name = d.anchor
    if (d.title) patch.title = d.title
    // 在线状态：录制中/准备中=直播中；其余（探测/空闲/完成/停止/失败）按 state 归位
    if (['recording', 'preparing'].includes(d.state)) patch.is_live = true
    else if (['finished', 'stopped', 'failed', 'idle'].includes(d.state)) patch.is_live = false
    applyEventToRoom(rid, patch)
  } else if (t === 'live_start') {
    applyEventToRoom(rid, { is_live: true, session_state: 'recording',
      anchor_name: d.anchor || undefined, title: d.title || undefined })
  } else if (t === 'live_end') {
    applyEventToRoom(rid, { is_live: false, session_state: 'finished' })
  } else if (t === 'rec_error') {
    const cur = rooms.value.find(x => x.id === rid)
    if (!cur || cur.session_state === 'recording') {
      applyEventToRoom(rid, { session_state: 'checking' })
    }
  }
}

let unsub = null
let pollTimer = null
onMounted(async () => {
  await load()
  if (!ws.connected) ws.connect()
  unsub = ws.subscribe(onWsEvent)
  // WS 断线时的兜底轮询（WS 正常时 WS 实时更新优先，轮询仅兜底）
  pollTimer = setInterval(() => { if (!ws.connected) load() }, 30000)
})
onUnmounted(() => {
  if (unsub) unsub()
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>

<style scoped>
.summary-bar {
  display: flex; align-items: center; gap: 18px; padding: 12px 18px; margin-bottom: 16px;
  background: var(--bg-soft); border: 1px solid var(--border-soft); border-radius: var(--r-md);
  flex-wrap: wrap;
}
.sum-item { font-size: 12px; color: var(--dim); display: flex; align-items: center; gap: 5px; }
.sum-item b { font-size: 15px; color: var(--text); font-variant-numeric: tabular-nums; }
.sum-item b.ok { color: var(--green); }
.sum-item b.live { color: var(--cyan); }
.sum-item b.imp { color: var(--purple); }
.filters { display: flex; gap: 8px; }
.cell-main { display: flex; align-items: center; gap: 4px; min-width: 0; }
.cell-main .nm { font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cell-title { display: block; color: var(--dim); font-size: 12.5px; max-width: 260px; }
.ellip { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nowrap { white-space: nowrap; }
.cell-tag { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: var(--panel-2, #1c2130); color: var(--dim-2); white-space: nowrap; flex-shrink: 0; }
.cell-sub { font-size: 11px; color: var(--dim-2); margin-top: 3px; display: flex; align-items: center; gap: 5px; }
.dot-sep { opacity: .4; }
/* 解析状态框 */
.resolve-box {
  display: flex; align-items: center; gap: 8px; font-size: 12.5px; padding: 9px 12px;
  border-radius: 9px; background: var(--panel-2); border: 1px solid var(--border-soft); color: var(--dim);
}
.resolve-box.ok { color: var(--green); border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.07); }
.resolve-box.err { color: var(--red); border-color: rgba(248,113,113,.35); background: rgba(248,113,113,.07); }
.resolve-box b { color: var(--text); word-break: break-all; }
.resolve-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.resolve-url { color: var(--text); word-break: break-all; font-size: 12px; }
.resolve-meta { color: var(--dim); font-size: 11.5px; }
.link-btn { background: none; border: none; color: var(--accent); font-size: 12px; cursor: pointer; margin-left: auto; flex-shrink: 0; }
.link-btn:hover { text-decoration: underline; }
.spinner {
  width: 13px; height: 13px; border: 2px solid rgba(79,140,255,.25); border-top-color: var(--accent);
  border-radius: 50%; animation: spin .7s linear infinite; display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg) } }
</style>