<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider placement="top-right">
      <n-dialog-provider>
        <div class="layout">
          <!-- ====== 侧边导航（分组） ====== -->
          <aside class="sidebar">
            <div class="brand">
              <div class="logo">
                <Video :size="20" :stroke-width="2" />
              </div>
              <div class="brand-txt">
                <h1>GirlRec</h1>
                <p>直播录制中心</p>
              </div>
            </div>

            <div class="nav-scroll">
              <template v-for="g in groups" :key="g.title">
                <p class="nav-group">
                  {{ g.title }}
                  <span class="g-count">{{ g.items.length }}</span>
                </p>
                <RouterLink
                  v-for="r in g.items" :key="r.path" :to="r.path"
                  class="nav-item" :class="{ active: isActive(r) }"
                >
                  <component :is="r.icon" class="icon" :size="16" :stroke-width="2" />
                  <span class="lbl">{{ r.label }}</span>
                  <span v-if="r.badge" class="nav-badge">{{ r.badge }}</span>
                </RouterLink>
              </template>
            </div>

            <div class="side-foot">
              <div class="ws-status">
                <span :class="['dot', connected ? 'on' : 'off']"></span>
                <span>{{ connected ? '实时通道已连接' : '实时通道断开' }}</span>
              </div>
              <div class="ver">v0.5 · 52 平台</div>
            </div>
          </aside>

          <!-- ====== 主区 ====== -->
          <div class="main">
            <header class="topbar">
              <div class="tb-left">
                <h2>{{ title }}</h2>
              </div>
              <div class="tb-right">
                <!-- 磁盘占用 -->
                <div class="disk" v-if="stats?.disk" :title="`录制目录磁盘使用 ${diskUsedPct}%`">
                  <HardDrive :size="14" :stroke-width="2" class="dim" />
                  <div class="disk-info">
                    <span class="disk-txt">磁盘 {{ diskUsedPct }}%</span>
                    <div class="progress thin"><i :style="{ width: diskUsedPct + '%', background: diskColor }"></i></div>
                  </div>
                </div>
                <!-- ffmpeg -->
                <span class="pill" :class="{ ok: stats?.ffmpeg, bad: !stats?.ffmpeg }" title="ffmpeg 可用性">
                  {{ stats?.ffmpeg ? 'ffmpeg ✓' : 'ffmpeg ✗' }}
                </span>
                <!-- 引擎 -->
                <span class="pill" :class="{ ok: engineOk }" title="后端引擎状态">
                  {{ engineOk ? '引擎正常' : '引擎离线' }}
                </span>
                <!-- 会话数 -->
                <span class="pill" title="实时会话">
                  {{ health?.sessions ?? stats?.sessions?.total ?? 0 }} 个会话
                </span>
              </div>
            </header>

            <main class="content">
              <RouterView />
            </main>
          </div>

          <ToastHost />
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, zhCN, dateZhCN } from 'naive-ui'
import { Video, HardDrive, LayoutDashboard, RadioTower, MonitorPlay, FolderOpen, Settings2, Blocks, Clapperboard, BellRing } from 'lucide-vue-next'
import { useWsStore } from './stores/ws'
import { useSysStore } from './stores/sys'
import ToastHost from './components/ToastHost.vue'

const route = useRoute()
const ws = useWsStore()
const sys = useSysStore()

const title = computed(() => route.meta?.title || 'GirlRec')
const connected = computed(() => ws.connected)
const health = computed(() => sys.health)
const stats = computed(() => sys.stats)

const engineOk = computed(() => health.value?.status === 'ok' || !!health.value)
const diskUsedPct = computed(() => stats.value?.disk?.used_pct ?? 0)
const diskColor = computed(() => {
  if (diskUsedPct.value >= 90) return 'var(--red)'
  if (diskUsedPct.value >= 75) return 'var(--amber)'
  return 'linear-gradient(90deg, var(--accent), var(--cyan))'
})

const groups = computed(() => [
  {
    title: '监控',
    items: [
      { path: '/', label: '总览', icon: LayoutDashboard },
      { path: '/live', label: '实时监控', icon: RadioTower },
    ],
  },
  {
    title: '管理',
    items: [
      { path: '/rooms', label: '直播间', icon: MonitorPlay },
      { path: '/recordings', label: '文件管理', icon: FolderOpen },
      { path: '/settings/rec', label: '录制设置', icon: Clapperboard },
      { path: '/platforms', label: '平台管理', icon: Blocks },
      { path: '/settings/push', label: '推送设置', icon: BellRing },
    ],
  },
])

function isActive(r) {
  return r.path === '/' ? route.path === '/' : route.path.startsWith(r.path)
}

// 设计语言：accent 只用于主操作/选中/状态，第二中性层给侧栏
const themeOverrides = {
  common: {
    primaryColor: '#4f8cff',
    primaryColorHover: '#6b9fff',
    primaryColorPressed: '#3f7cf0',
    primaryColorSuppl: '#4f8cff',
    borderRadius: '9px',
    fontSize: '13.5px',
  },
  Card: { borderRadius: '12px' },
  DataTable: { borderRadius: '12px' },
}

let timer
onMounted(() => {
  ws.connect()
  sys.refreshHealth()
  sys.refreshStats()
  timer = setInterval(() => {
    sys.refreshHealth()
    sys.refreshStats()
  }, 15000)
})
onUnmounted(() => { clearInterval(timer); ws.close() })
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased;
}
.layout { display: flex; min-height: 100vh; }

/* ---- 侧边栏 ---- */
.sidebar {
  width: 224px; background: var(--bg-soft); border-right: 1px solid var(--border-soft);
  display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; flex-shrink: 0;
}
.brand { padding: 20px 18px 16px; border-bottom: 1px solid var(--border-soft); display: flex; align-items: center; gap: 12px; }
.brand .logo {
  font-size: 24px; width: 40px; height: 40px; border-radius: 11px; color: #fff;
  background: linear-gradient(135deg, var(--accent), var(--cyan));
  display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 14px rgba(79,140,255,.35);
}
.brand h1 { font-size: 18px; font-weight: 700; letter-spacing: .3px; }
.brand p { font-size: 11px; color: var(--dim); margin-top: 1px; }
.nav-scroll { flex: 1; overflow-y: auto; padding: 10px 10px 14px; }
.nav-group { font-size: 11px; color: var(--dim-2); text-transform: uppercase; letter-spacing: 1px; padding: 14px 10px 6px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.nav-group .g-count { font-size: 10px; background: var(--panel-2); color: var(--dim-2); border-radius: 99px; padding: 0 6px; line-height: 1.5; font-weight: 600; }
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 9px;
  color: var(--dim); text-decoration: none; font-size: 13.5px; margin-bottom: 2px;
  transition: background .15s ease, color .15s ease;
}
.nav-item:hover { background: var(--panel-2); color: var(--text); }
.nav-item .icon { color: inherit; opacity: .75; transition: opacity .15s ease; }
.nav-item.active { background: var(--accent-soft); color: var(--accent-text); font-weight: 600; }
.nav-item.active .icon { opacity: 1; color: var(--accent); }
.nav-badge { margin-left: auto; font-size: 10px; background: var(--accent); color: #fff; border-radius: 99px; padding: 1px 7px; font-weight: 700; }
.side-foot { padding: 14px 18px; border-top: 1px solid var(--border-soft); }
.ws-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--dim); }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot.on { background: var(--green); box-shadow: 0 0 8px rgba(52,211,153,.7); }
.dot.off { background: var(--red); }
.ver { margin-top: 8px; font-size: 11px; color: var(--dim-2); }

/* ---- 主区 ---- */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar {
  height: 60px; display: flex; align-items: center; justify-content: space-between; gap: var(--sp-4);
  padding: 0 26px; background: var(--bg-soft); border-bottom: 1px solid var(--border-soft);
  position: sticky; top: 0; z-index: 50;
}
.tb-left { display: flex; align-items: center; min-width: 0; }
.tb-left h2 { font-size: 17px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tb-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.disk { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 10px; background: var(--panel); border: 1px solid var(--border-soft); }
.disk-ic { font-size: 14px; line-height: 1; }
.disk-info { display: flex; flex-direction: column; gap: 3px; min-width: 96px; justify-content: center; }
.disk-txt { font-size: 11px; color: var(--dim); font-variant-numeric: tabular-nums; line-height: 1; }
.disk-info .progress { height: 4px; }
.pill {
  font-size: 12px; padding: 5px 12px; border-radius: 99px; background: var(--panel); color: var(--dim);
  border: 1px solid var(--border-soft); font-variant-numeric: tabular-nums; white-space: nowrap;
  display: inline-flex; align-items: center; line-height: 1.4;
}
.pill.ok { color: var(--green); border-color: rgba(52,211,153,.3); }
.pill.bad { color: var(--red); border-color: rgba(248,113,113,.35); }
.content { padding: 24px 26px 40px; flex: 1; }

@media (max-width: 900px) {
  .sidebar { width: 64px; }
  .brand-txt, .nav-item .lbl, .nav-group, .side-foot .ver { display: none; }
  .content { padding: 16px; }
}
</style>