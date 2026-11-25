<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>实时监控</h2>
        <p class="sub">所有直播间的实时状态与录制进度（WS 推送）</p>
      </div>
      <div class="actions">
        <span :class="['tag', connected ? 'green' : 'red']">
          <span v-if="connected" class="dotp"></span>
          {{ connected ? '实时推送已连接' : '推送已断开' }}
        </span>
      </div>
    </div>

    <!-- 汇总条 -->
    <div class="summary-row">
      <div class="sum-card" v-for="c in summary" :key="c.label">
        <span class="dot" :style="{ background: c.color }"></span>
        <b class="num">{{ c.count }}</b>
        <span class="dim">{{ c.label }}</span>
      </div>
    </div>

    <!-- 会话卡片墙 -->
    <template v-if="sessions.length">
      <div class="grid">
        <div v-for="s in sessions" :key="s.room_id" class="sess-card" :class="'st-' + stateKey(s.state)">
          <div class="sess-head">
            <span class="tag" :class="tagCls(s.state)">
              <span v-if="s.state === 'recording'" class="dotp"></span>{{ stateText(s.state) }}
            </span>
            <strong class="ellip">{{ s.anchor || '未知主播' }}</strong>
            <span class="grow"></span>
            <span class="dim" style="font-size:11px">{{ s.platform }}</span>
          </div>

          <div class="sess-title ellip" v-if="s.title">{{ s.title }}</div>
          <div class="sess-url mono ellip dim">{{ s.url }}</div>

          <div class="sess-meta" v-if="s.state === 'recording'">
            <span><Clock :size="13" :stroke-width="2" /> {{ fmtClock(s.duration_seconds) }}</span>
            <span><Database :size="13" :stroke-width="2" /> {{ fmtSize(s.file_size) }}</span>
            <span><Zap :size="13" :stroke-width="2" /> {{ fmtBitrate(s.bitrate_kbps) }}</span>
          </div>
          <div class="progress mt-3" v-if="s.state === 'recording'">
            <i :style="{ width: pct(s) + '%' }"></i>
          </div>

          <div class="sess-err" v-if="s.error"><AlertTriangle :size="14" :stroke-width="2" /> {{ s.error }}</div>

          <div class="sess-foot" v-if="s.record_url || s.save_file_path">
            <span class="dim small ellip" :title="s.record_url">流：{{ s.record_url }}</span>
            <span class="dim small ellip" :title="s.save_file_path">存：{{ s.save_file_path }}</span>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="card"><div class="empty">
      <div class="big"><RadioTower :size="34" :stroke-width="1.6" /></div>
      暂无活动会话<br /><span class="dim">添加直播间并启用后自动出现在这里</span>
    </div></div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { useWsStore } from '../stores/ws'
import { RadioTower, Clock, Database, Zap, AlertTriangle } from 'lucide-vue-next'
import { fmtClock, fmtSize, fmtBitrate } from '../utils/format'

const ws = useWsStore()
const connected = computed(() => ws.connected)
const sessions = ref([])

const summary = computed(() => {
  const mk = (state) => sessions.value.filter(s => stateKey(s.state) === state).length
  return [
    { label: '录制中', count: mk('rec'), color: 'var(--green)' },
    { label: '探测中', count: mk('warn'), color: 'var(--amber)' },
    { label: '已结束', count: mk('off'), color: 'var(--dim-2)' },
    { label: '异常', count: mk('fail'), color: 'var(--red)' },
  ]
})

function stateKey(s) {
  if (['recording'].includes(s)) return 'rec'
  if (['checking', 'preparing'].includes(s)) return 'warn'
  if (['failed', 'stopped'].includes(s)) return 'fail'
  return 'off'
}
function stateText(s) {
  return { checking: '探测中', preparing: '准备中', recording: '录制中', idle: '空闲', stopped: '已停止', finished: '已完成', failed: '失败' }[s] || s
}
function tagCls(s) {
  return { checking: 'amber', preparing: 'amber', recording: 'green', failed: 'red', stopped: 'gray', finished: 'gray', idle: 'gray' }[s] || 'gray'
}
function pct(s) { return Math.min(100, (s.duration_seconds || 0) / 3600 * 100) }

function onEvent(evt) {
  if (evt.type !== 'session_update') return
  const d = evt.data || {}
  const idx = sessions.value.findIndex(s => s.room_id === d.room_id)
  if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...d }
  else sessions.value.unshift({ room_id: d.room_id, anchor: d.anchor, platform: d.platform, ...d })
  sessions.value = sessions.value.slice(0, 50)
}

let unsub = null
onMounted(async () => {
  unsub = ws.subscribe(onEvent)
  try { sessions.value = await api.listSessions() } catch (e) { console.error(e) }
})
onUnmounted(() => { if (unsub) unsub() })
</script>

<style scoped>
.summary-row { display: flex; gap: var(--sp-3); flex-wrap: wrap; margin-bottom: var(--sp-5); }
.sum-card {
  display: flex; align-items: center; gap: 8px; padding: 10px 16px;
  background: var(--panel); border: 1px solid var(--border-soft); border-radius: var(--r-md);
}
.sum-card b { font-size: 16px; font-variant-numeric: tabular-nums; }
.sum-card .dot { width: 8px; height: 8px; border-radius: 50%; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.sess-card {
  background: var(--panel); border: 1px solid var(--border-soft); border-radius: var(--r-lg);
  padding: 16px 18px; display: flex; flex-direction: column; gap: 9px;
  transition: border-color .2s, transform .15s;
}
.sess-card:hover { transform: translateY(-2px); }
.sess-card.st-rec { border-color: rgba(52,211,153,.4); box-shadow: 0 0 0 1px rgba(52,211,153,.12), var(--shadow); }
.sess-card.st-warn { border-color: rgba(251,191,36,.3); }
.sess-card.st-fail { border-color: rgba(248,113,113,.35); }
.sess-head { display: flex; align-items: center; gap: 10px; }
.sess-head strong { font-size: 14px; min-width: 0; }
.sess-title { font-size: 13px; color: var(--text); }
.sess-url { font-size: 11px; }
.sess-meta { display: flex; gap: 16px; font-size: 12px; color: var(--text); font-variant-numeric: tabular-nums; }
.sess-err { font-size: 12px; color: var(--red); background: var(--red-soft); border-radius: 8px; padding: 6px 10px; word-break: break-all; }
.sess-foot { display: flex; flex-direction: column; gap: 2px; border-top: 1px solid var(--border-soft); padding-top: 8px; }
</style>