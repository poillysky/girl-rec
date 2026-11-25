<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>文件管理</h2>
        <p class="sub">成品库 · 已合并完成的完整 MP4 · 可播放 / 下载 / 删除</p>
      </div>
      <div class="actions">
        <span class="tag gray">共 {{ filtered.length }} 个</span>
        <span class="tag purple">{{ fmtSize(totalSize) }}</span>
      </div>
    </div>

    <!-- 筛选条 -->
    <div class="filter-bar">
      <input v-model.trim="kw" class="input" style="width:240px" placeholder="搜索平台 / 主播 / 标题 / 文件名" />
      <Dropdown v-model="platFilter" :options="platformOpts" placeholder="全部平台" width="150px" />
      <Dropdown v-model="anchorFilter" :options="anchorOpts" placeholder="全部主播" width="170px" />
      <Dropdown v-model="statusFilter" :options="statusOpts" placeholder="全部状态" width="130px" />
      <div class="grow"></div>
      <button class="btn sm" @click="reload" :disabled="loading"><RefreshCw :size="13" :stroke-width="2" :class="{ spin: loading }" /> 刷新</button>
    </div>

    <section class="card">
      <div class="table-wrap">
        <table class="table rec-table">
          <colgroup>
            <col style="width:76px" />
            <col style="width:120px" />
            <col />
            <col style="width:96px" />
            <col style="width:96px" />
            <col style="width:100px" />
            <col style="width:158px" />
            <col style="width:124px" />
          </colgroup>
          <thead>
            <tr>
              <th>平台</th>
              <th>主播</th>
              <th class="ta-l">标题 / 文件名</th>
              <th class="num">大小</th>
              <th class="num nowrap">时长</th>
              <th>状态</th>
              <th>录制时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in filtered" :key="r.id">
              <td><span class="tag blue">{{ r.platform }}</span></td>
              <td>{{ r.anchor_name || '—' }}</td>
              <td class="ta-l">
                <span class="cell-title ellip" :title="r.file_name">
                  {{ r.title || r.file_name }}
                </span>
              </td>
              <td class="num">{{ fmtSize(r.file_size) }}</td>
              <td class="num nowrap">{{ fmtDur(r.duration_seconds) }}</td>
              <td>
                <span class="tag nowrap" :class="r.exists ? 'green' : 'red'">
                  <span v-if="r.exists" class="dotp"></span>{{ r.exists ? '正常' : '文件缺失' }}
                </span>
              </td>
              <td class="dim nowrap">{{ r.start_time ? fmtTime(r.start_time, true) : (r.created_at ? fmtTime(r.created_at, true) : '—') }}</td>
              <td class="ops">
                <button class="icon-btn" title="播放" :disabled="!r.exists" @click="play(r)"><Play :size="15" /></button>
                <a class="icon-btn" title="下载" :class="{ disabled: !r.exists }"
                   :href="r.exists ? api.downloadUrl(r.id) : undefined" :download="r.file_name">
                  <Download :size="15" />
                </a>
                <button class="icon-btn danger" title="删除" @click="askRemove(r)"><Trash2 :size="15" /></button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!filtered.length" class="empty">
        <div class="big"><component :is="loading ? IcLoader : IcFolderOpen" :size="34" :stroke-width="1.6" :class="{ spin: loading }" /></div>
        {{ loading ? '加载中…' : (all.length ? '没有匹配的录制文件' : '还没有成品，直播间开播并录满一段后会合并出完整 MP4 出现在这里') }}
      </div>
    </section>

    <!-- 播放弹窗 -->
    <div v-if="playing" class="modal-mask" @click.self="closePlayer">
      <div class="player-modal">
        <div class="player-head">
          <span class="ellip">{{ playing.anchor_name }} · {{ playing.title || playing.file_name }}</span>
          <button class="icon-btn" @click="closePlayer"><X :size="18" /></button>
        </div>
        <video :src="api.streamUrl(playing.id)" controls autoplay class="player-video"></video>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="delTarget" class="modal-mask" @click.self="delTarget = null">
      <div class="confirm-modal">
        <div class="confirm-title">删除成品</div>
        <p class="confirm-body">
          确认删除 <strong>{{ delTarget.file_name }}</strong>？
          <br />将同时删除数据库记录和磁盘上的 MP4 文件（{{ fmtSize(delTarget.file_size) }}），不可恢复。
        </p>
        <div class="confirm-actions">
          <button class="btn" @click="delTarget = null">取消</button>
          <button class="btn danger" :disabled="busy" @click="doRemove">{{ busy ? '删除中…' : '确认删除' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api'
import { toast } from '../utils/toast'
import { RefreshCw, FolderOpen, Loader2, Play, Download, Trash2, X } from 'lucide-vue-next'
import Dropdown from '../components/Dropdown.vue'
import { fmtSize, fmtDur, fmtTime } from '../utils/format'

const IcLoader = Loader2
const IcFolderOpen = FolderOpen

const all = ref([])
const kw = ref('')
const statusFilter = ref('')
const platFilter = ref('')
const anchorFilter = ref('')
const loading = ref(false)
const playing = ref(null)
const delTarget = ref(null)
const busy = ref(false)

const platforms = computed(() => [...new Set(all.value.map(r => r.platform).filter(Boolean))].sort())

// 下拉组件选项
const platformOpts = computed(() => [
  { label: '全部平台', value: '' },
  ...platforms.value.map(p => ({ label: p, value: p })),
])
const anchorOpts = computed(() => {
  // 主播按当前平台筛选后去重（若选了平台只列该平台主播）
  const pool = platFilter.value ? all.value.filter(r => r.platform === platFilter.value) : all.value
  const names = [...new Set(pool.map(r => r.anchor_name).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh'))
  return [{ label: '全部主播', value: '' }, ...names.map(n => ({ label: n, value: n }))]
})
const statusOpts = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'ready' },
  { label: '文件缺失', value: 'missing' },
]

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return all.value.filter(r => {
    if (platFilter.value && r.platform !== platFilter.value) return false
    if (anchorFilter.value && r.anchor_name !== anchorFilter.value) return false
    if (statusFilter.value === 'ready' && !r.exists) return false
    if (statusFilter.value === 'missing' && r.exists) return false
    if (!k) return true
    return [r.platform, r.anchor_name, r.title, r.file_name, r.file_path].some(v => (v || '').toLowerCase().includes(k))
  })
})
const totalSize = computed(() => filtered.value.reduce((a, r) => a + (r.file_size || 0), 0))

// 切换平台时，若当前选中主播不属于该平台则重置
watch(platFilter, () => {
  if (anchorFilter.value && !anchorOpts.value.some(o => o.value === anchorFilter.value)) {
    anchorFilter.value = ''
  }
})

async function reload() {
  loading.value = true
  try { all.value = await api.listRecordings({ limit: 500 }) }
  catch (e) { toast.err(e.message) }
  finally { loading.value = false }
}

function play(r) { playing.value = r }
function closePlayer() { playing.value = null }

function askRemove(r) { delTarget.value = r }
async function doRemove() {
  busy.value = true
  try {
    await api.deleteProduct(delTarget.value.id, true)
    toast.ok('已删除成品')
    delTarget.value = null
    await reload()
  } catch (e) { toast.err(e.message) }
  finally { busy.value = false }
}

onMounted(reload)
</script>

<style scoped>
.filter-bar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.cell-title { max-width: 300px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.nowrap { white-space: nowrap; }
.rec-table th, .rec-table td { overflow: hidden; }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.ops { display: flex; gap: 4px; justify-content: center; }
.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 7px; border: 1px solid var(--border-soft);
  background: transparent; color: var(--dim); cursor: pointer; transition: all 0.15s;
  text-decoration: none;
}
.icon-btn:hover { color: var(--text); background: var(--panel-2); border-color: var(--border); }
.icon-btn.danger:hover { color: #ff6b6b; border-color: #ff6b6b55; background: #ff6b6b12; }
.icon-btn.disabled, .icon-btn:disabled { opacity: 0.3; pointer-events: none; }

.modal-mask {
  position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.72);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.player-modal {
  width: min(1000px, 92vw); background: #000; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--border); display: flex; flex-direction: column;
}
.player-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; background: var(--panel); color: var(--text); font-size: 13px;
}
.player-head .ellip { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.player-video { width: 100%; max-height: 78vh; background: #000; display: block; }

.confirm-modal {
  width: min(420px, 92vw); background: var(--panel); border-radius: 12px;
  border: 1px solid var(--border); padding: 22px;
}
.confirm-title { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 10px; }
.confirm-body { font-size: 13px; color: var(--dim); line-height: 1.7; margin-bottom: 18px; }
.confirm-body strong { color: var(--text); word-break: break-all; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 10px; }
.btn.danger { background: #e5484d; color: #fff; border-color: #e5484d; }
.btn.danger:hover:not(:disabled) { background: #cf3d42; }
</style>
