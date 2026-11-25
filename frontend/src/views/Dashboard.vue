<template>
  <div class="page">
    <!-- ====== 头部 ====== -->
    <div class="page-head">
      <div>
        <h2>总览</h2>
        <p class="sub">引擎与录制状态一屏掌握</p>
      </div>
      <div class="actions">
        <button class="btn ghost sm" @click="refreshAll" :disabled="loading"><RefreshCw :size="14" :stroke-width="2" />{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>

    <!-- ====== 统计卡片（真实数据） ====== -->
    <div class="stat-grid">
      <div class="stat">
        <div class="ic" style="background:var(--accent-soft)"><MonitorPlay :size="18" :stroke-width="2" /></div>
        <div class="info">
          <div class="num">{{ stats?.rooms?.total ?? '—' }}</div>
          <div class="lbl">直播间</div>
          <div class="sub">{{ stats?.rooms?.enabled ?? 0 }} 启用 · {{ stats?.rooms?.important ?? 0 }} 重要</div>
        </div>
      </div>
      <div class="stat">
        <div class="ic" style="background:var(--green-soft)"><RadioTower :size="18" :stroke-width="2" /></div>
        <div class="info">
          <div class="num" :class="{ live: stats?.rooms?.live }">{{ stats?.rooms?.live ?? '—' }}</div>
          <div class="lbl">直播中</div>
          <div class="sub">实时探测结果</div>
        </div>
      </div>
      <div class="stat">
        <div class="ic" style="background:var(--cyan-soft)"><Activity :size="18" :stroke-width="2" /></div>
        <div class="info">
          <div class="num">{{ stats?.sessions?.recording ?? 0 }}<span class="dim" style="font-size:13px">/{{ stats?.sessions?.total ?? 0 }}</span></div>
          <div class="lbl">录制会话</div>
          <div class="sub">{{ stats?.sessions?.checking ?? 0 }} 探测中</div>
        </div>
      </div>
      <div class="stat">
        <div class="ic" style="background:var(--purple-soft)"><FolderOpen :size="18" :stroke-width="2" /></div>
        <div class="info">
          <div class="num">{{ stats?.recordings?.total ?? '—' }}</div>
          <div class="lbl">录制文件</div>
          <div class="sub">{{ fmtSize(stats?.recordings?.total_size) }} · {{ fmtDur(stats?.recordings?.total_duration) }}</div>
        </div>
      </div>
      <div class="stat">
        <div class="ic" style="background:var(--amber-soft)"><HardDrive :size="18" :stroke-width="2" /></div>
        <div class="info">
          <div class="num">{{ diskPct }}<span class="dim" style="font-size:14px">%</span></div>
          <div class="lbl">磁盘占用</div>
          <div class="sub">{{ fmtSize(freeBytes) }} 可用</div>
        </div>
      </div>
    </div>

    <div class="two-col mt-5">
      <!-- ====== 直播中/实时会话 ====== -->
      <section class="card">
        <div class="card-head">
          <h3><span class="ic"><RadioTower :size="15" :stroke-width="2" /></span>实时会话</h3>
          <span class="extra"><span class="tag blue" v-if="connected">实时推送</span><span class="tag gray" v-else>已断开</span></span>
        </div>
        <div class="card-body">
          <div v-if="liveList.length">
            <div v-for="s in liveList" :key="s.room_id" class="live-item">
              <div class="li-top">
                <span :class="['tag', 'green', stateTagClass(s) === 'warn' ? 'amber' : '']">
                  <span class="dotp"></span>{{ stateText(s.state) }}
                </span>
                <strong class="ellip grow">{{ s.anchor }}</strong>
                <span class="dim">{{ s.platform }}</span>
              </div>
              <div class="li-mid dim" v-if="s.title">{{ s.title }}</div>
              <div class="li-mid">
                <span v-if="s.duration_seconds != null" class="num mono">{{ fmtClock(s.duration_seconds) }}</span>
                <span v-if="s.file_size != null">{{ fmtSize(s.file_size) }}</span>
                <span v-if="s.bitrate_kbps != null">{{ fmtBitrate(s.bitrate_kbps) }}</span>
              </div>
              <div class="progress"><i :style="{ width: progPct(s) + '%' }"></i></div>
            </div>
          </div>
          <div v-else class="empty"><div class="big">📡</div>暂无活跃会话<br /><span class="dim">直播间开播后这里会实时展示</span></div>
        </div>
      </section>

      <!-- ====== 最近事件 ====== -->
      <section class="card">
        <div class="card-head">
          <h3><span class="ic"><ListTodo :size="15" :stroke-width="2" /></span>最近事件</h3>
          <RouterLink to="/live" class="extra">进入实时监控 →</RouterLink>
        </div>
        <div class="card-body pd-0">
          <div v-if="events.length" class="ev-list">
            <div v-for="e in events" :key="e.id" class="ev-item">
              <span class="ev-ic" :style="{ background: evBg(e.type) }"><component :is="evIcon(e.type)" :size="15" :stroke-width="2" /></span>
              <div class="ev-main">
                <div class="ev-content">{{ e.content }}</div>
                <div class="ev-meta dim">{{ e.platform }} · {{ fmtAgo(e.created_at) }}</div>
              </div>
            </div>
          </div>
          <div v-else class="empty"><div class="big"><ListTodo :size="34" :stroke-width="1.6" /></div>暂无事件记录</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { useWsStore } from '../stores/ws'
import { useSysStore } from '../stores/sys'
import { RadioTower, ListTodo, RefreshCw, MonitorPlay, Activity, FolderOpen, HardDrive, Play, Square, CheckCircle2, XCircle, BarChart3, KeyRound, Rocket, Info } from 'lucide-vue-next'
import { fmtSize, fmtDur, fmtClock, fmtAgo, fmtBitrate } from '../utils/format'

const ws = useWsStore()
const sys = useSysStore()
const stats = computed(() => sys.stats)
const connected = computed(() => ws.connected)

const sessions = ref([])
const events = ref([])
const loading = ref(false)

const liveList = computed(() => sessions.value.filter(s => ['checking', 'preparing', 'recording'].includes(s.state)))
const diskPct = computed(() => stats.value?.disk?.used_pct ?? 0)
const freeBytes = computed(() => (stats.value?.disk?.free_gb ?? 0) * 1024 ** 3)

function progPct(s) {
  if (s.duration_seconds == null) return 0
  return Math.min(100, (s.duration_seconds / 3600) * 100)
}
function stateText(s) {
  return { checking: '探测中', preparing: '准备中', recording: '录制中', stopped: '已停止', failed: '失败', finished: '已完成', idle: '空闲' }[s] || s
}
function stateTagClass(s) {
  return { checking: 'amber', preparing: 'amber', recording: 'green', failed: 'red' }[s] || 'gray'
}
const EV_ICONS = {
  live_start: Play, live_end: Square, rec_finish: CheckCircle2, rec_error: XCircle,
  session_update: BarChart3, cookie_invalid: KeyRound, engine_start: Rocket, disk_low: HardDrive,
}
function evIcon(t) { return EV_ICONS[t] || Info }
function evBg(t) {
  return { live_start: 'var(--green-soft)', live_end: 'var(--gray-soft, var(--panel-2))', rec_finish: 'var(--accent-soft)', rec_error: 'var(--red-soft)', cookie_invalid: 'var(--amber-soft)' }[t] || 'var(--panel-2)'
}

function onEvent(evt) {
  // 实时会话进度合并
  if (evt.type === 'session_update') {
    const d = evt.data || {}
    const idx = sessions.value.findIndex(s => s.room_id === d.room_id)
    if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...d }
    else sessions.value.unshift({ room_id: d.room_id, anchor: d.anchor, platform: d.platform, ...d })
  }
  // 事件头部插入
  if (evt.type && evt.type !== 'session_update') {
    events.value.unshift({ id: 'ev' + Date.now() + Math.random(), type: evt.type, content: evt.data?.msg || evt.content || evt.type, platform: evt.data?.platform || evt.platform || '', created_at: new Date().toISOString() })
    events.value = events.value.slice(0, 30)
  }
}

async function loadSessions() {
  try { sessions.value = await api.listSessions() } catch (e) { console.error(e) }
}
async function loadEvents() {
  try { events.value = await api.listEvents() } catch (e) { /* 无事件接口时降级 */ }
}
async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([sys.refreshStats(), loadSessions(), loadEvents()])
  } finally { loading.value = false }
}

let unsub = null
onMounted(() => {
  unsub = ws.subscribe(onEvent)
  loadSessions(); loadEvents()
})
onUnmounted(() => { if (unsub) unsub() })
</script>

<style scoped>
.live-item { padding: 12px 0; border-bottom: 1px solid var(--border-soft); display: flex; flex-direction: column; gap: 8px; }
.live-item:last-child { border-bottom: none; padding-bottom: 0; }
.li-top { display: flex; align-items: center; gap: 10px; }
.li-top strong { min-width: 0; }
.li-mid { display: flex; gap: 18px; font-size: 12px; color: var(--dim); font-variant-numeric: tabular-nums; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-5); align-items: start; }
.pd-0 { padding: 0 var(--sp-5) var(--sp-3); }
.ev-list { max-height: 430px; overflow-y: auto; }
.ev-item { display: flex; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--border-soft); }
.ev-item:last-child { border-bottom: none; }
.ev-ic { width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
.ev-main { flex: 1; min-width: 0; }
.ev-content { font-size: 13px; line-height: 1.45; word-break: break-all; }
.ev-meta { margin-top: 3px; font-size: 11px; }
.num.live { color: var(--green); }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } }
</style>