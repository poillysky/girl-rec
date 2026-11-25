<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>{{ pageTitle }}</h2>
        <p class="sub">{{ pageSub }}</p>
      </div>
      <div class="actions">
        <span class="tag gray">共 {{ totalCount }} 项</span>
      </div>
    </div>

    <!-- Tab 导航（多组模式才显示；单组模式隐藏） -->
    <div class="tabs" v-if="!onlyGroup">
      <button v-for="t in TABS" :key="t.name" class="tab" :class="{ active: activeTab === t.name }"
              @click="onTab(t.name)">
        <component :is="t.icon" :size="15" :stroke-width="2" />
        <span>{{ t.title }}</span>
        <span class="tab-count">{{ countOf(t.name) }}</span>
      </button>
    </div>

    <!-- 搜索 -->
    <div class="filter-bar">
      <input v-model.trim="kw" class="input" style="width:280px" :placeholder="`在「${activeTabTitle}」中搜索`" />
      <div class="grow"></div>
      <span class="hint">{{ kw ? '匹配 ' + flatCount + ' 项' : '' }}</span>
    </div>

    <!-- 空态 -->
    <div v-if="!sections.length" class="card"><div class="empty">
      <div class="big"><component :is="activeTabObj.icon" :size="34" :stroke-width="1.6" /></div>
      {{ kw ? '没有匹配的配置项' : '该分类暂无配置项' }}
    </div></div>

    <!-- 紧凑小节列表：点开弹窗编辑 -->
    <div v-if="sections.length" class="sec-list">
      <button v-for="sec in sections" :key="sec.title" class="sec-row" type="button"
              @click="openSec(sec)">
        <span class="sec-ic-box"><component :is="sec.icon" :size="17" :stroke-width="1.9" /></span>
        <span class="sec-main">
          <span class="sec-title">{{ sec.title }}</span>
        </span>
        <span class="sec-count">{{ sec.items.length }} 项</span>
        <span v-if="secHasDirty(sec)" class="sec-dirty-dot" title="有未保存改动"></span>
        <ChevronRight :size="16" :stroke-width="2" class="sec-arrow" />
      </button>
    </div>

    <!-- 编辑弹窗 -->
    <div v-if="editSec" class="modal-mask" @click.self="closeSec">
      <div class="modal cfg-modal">
        <div class="modal-head">
          <h3>
            <component :is="editSec.icon" :size="16" :stroke-width="2" class="sec-ic" style="margin-right:6px" />
            {{ editSec.title }}
            <span class="badge" style="margin-left:8px">{{ editSec.items.length }}</span>
          </h3>
          <button class="x" @click="closeSec" aria-label="关闭"><X :size="16" :stroke-width="2" /></button>
        </div>
        <div class="modal-body">
          <div class="cfg-grid">
            <div v-for="c in editSec.items" :key="c.key" class="cfg-row">
              <div class="cfg-label-cell">
                <span class="cfg-label">{{ isCookieTab ? platformName(c.key) : labelOf(c.key) }}</span>
              </div>
              <div class="cfg-input-cell">
                <div class="cfg-ctrl" :class="{ 'is-wide': fieldType(c.key) === 'platforms' || c.key.endsWith('自定义脚本执行命令') }">
                  <!-- 布尔开关（非wide时靠右） -->
                  <button v-if="fieldType(c.key) === 'bool'"
                          role="switch" :aria-checked="drafts[c.key] === '是'"
                          :aria-label="labelOf(c.key)"
                          :class="['switch', 'switch-right', drafts[c.key] === '是' ? 'on' : '']"
                          @click="drafts[c.key] = drafts[c.key] === '是' ? '否' : '是'"
                          @keydown.enter.prevent="drafts[c.key] = drafts[c.key] === '是' ? '否' : '是'"
                          @keydown.space.prevent="drafts[c.key] = drafts[c.key] === '是' ? '否' : '是'"></button>
                  <!-- 平台多选 -->
                  <PlatformPicker v-else-if="fieldType(c.key) === 'platforms'"
                                  v-model="drafts[c.key]" :aria-label="labelOf(c.key)" />
                  <!-- 枚举下拉 -->
                  <Dropdown v-else-if="fieldType(c.key) === 'select'"
                            v-model="drafts[c.key]" :options="optionsFor(c.key)"
                            :aria-label="labelOf(c.key)" />
                  <!-- 普通文本 -->
                  <input v-else v-model="drafts[c.key]" class="input mono cell-input"
                         :size="isSecret(c.key) ? 20 : Math.min(60, Math.max(12, (drafts[c.key] || '').length + 3))"
                         :type="isSecret(c.key) ? 'password' : 'text'"
                         :autocomplete="isSecret(c.key) ? 'new-password' : 'off'"
                         :aria-label="labelOf(c.key)"
                         :inputmode="isProxyAddr(c.key) ? 'url' : 'text'"
                         :placeholder="placeholderOf(c.key)" />
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="closeSec">取消</button>
          <button class="btn primary" :disabled="!secDirty(editSec)" @click="saveEditSec">
            <Save :size="13" :stroke-width="2" /> {{ secDirty(editSec) ? '保存' : '已保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 未保存改动离开确认 -->
    <div v-if="showDiscard" class="modal-mask" @click.self="cancelDiscard" style="z-index:2100">
      <div class="modal" style="width:360px">
        <div class="modal-head"><h3>放弃修改？</h3><button class="x" @click="cancelDiscard" aria-label="关闭"><X :size="16" :stroke-width="2" /></button></div>
        <div class="modal-body"><p style="font-size:13px;color:var(--dim)">该分类有未保存的修改，关闭后将丢失。</p></div>
        <div class="modal-foot">
          <button class="btn" @click="cancelDiscard">继续编辑</button>
          <button class="btn primary" @click="confirmDiscard">放弃修改</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import PlatformPicker from '../components/PlatformPicker.vue'
import { toast } from '../utils/toast'
import {
  Save, Clapperboard, BellRing, KeyRound, Cookie, Wrench,
  Globe, SlidersHorizontal, FolderTree, Scissors, Film, Terminal, Gauge, Server, Send,
  X, ChevronRight
} from 'lucide-vue-next'
import { fmtTime } from '../utils/format'
import Dropdown from '../components/Dropdown.vue'

const props = defineProps({
  onlyGroup: { type: String, default: '' },   // '录制设置' / '推送配置' / ''(全部)
})

const all = ref([])
const kw = ref('')
const drafts = ref({})       // key -> 编辑中的值
const editSec = ref(null)    // 当前弹窗编辑的小节
const activeTab = ref(props.onlyGroup || '录制设置')

const TABS = [
  { name: '录制设置', title: '录制设置', icon: Clapperboard, match: ['录制设置'] },
  { name: '推送配置', title: '消息推送', icon: BellRing, match: ['推送配置'] },
  { name: '账号密码', title: '账号密码', icon: KeyRound, match: ['账号密码'] },
  { name: 'Cookie', title: '平台 Cookie / Token', icon: Cookie, match: ['Cookie', 'Authorization'] },
  { name: '其他', title: '其他', icon: Wrench, match: [] },
]

// 二级语义小节：按配置项短名（冒号后）精确/包含匹配归入小节
// 顺序即展示顺序；未匹配任何规则的归入该 tab 的兜底小节
const SECTION_RULES = {
  录制设置: [
    { title: '基础', icon: SlidersHorizontal, desc: '画质偏好与命名',
      keys: ['原画|超清|高清|标清|流畅', '是否去除名称中的表情符号'] },
    { title: '代理设置', icon: Globe,
      keys: ['是否使用代理ip(是/否)', '代理地址', '是否跳过代理检测(是/否)'] },
    { title: '保存与命名', icon: FolderTree, desc: '文件保存位置、目录结构、命名规则',
      keys: ['保存文件夹是否以作者区分', '保存文件夹是否以时间区分',
             '保存文件夹是否以标题区分', '保存文件名是否包含标题'] },
    { title: '流类型分片', icon: Film, desc: '不同流类型录制时用的容器格式（HLS/FLV/Agora… 各指定）',
      keys: ['HLS流分片格式', 'FLV流分片格式', 'Agora流分片格式', '视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频'] },
    { title: '分段与时长', icon: Scissors, desc: '分段录制、单次录制上限（到时自动生成成品并续录）',
      keys: ['分段录制是否开启', '视频分段时间(秒)', '单次录制最大时长(秒)', '单次录制最大大小(mb)'],
      optional: true },
    { title: '转码与后处理', icon: Film, desc: '录制结束后的成品处理',
      keys: ['录制完成后自动转为mp4格式', 'mp4格式重新编码为h264', '追加格式后删除原文件',
             '生成时间字幕文件', '是否录制完成后执行自定义脚本', '自定义脚本执行命令'] },
    { title: '网络与检测', icon: Gauge, desc: '探测频率与并发控制',
      keys: ['同一时间访问网络的线程数', '循环时间(秒)', '排队读取网址时间(秒)',
             '是否显示循环秒数', '是否显示直播源地址', '录制空间剩余阈值(gb)', '是否强制启用https录制'] },
    { title: '库目录', icon: Server, desc: '下载缓存库（录制中 ts 分片）与成品库（最终 MP4）目录',
      keys: ['缓存目录(不填则默认)', '成品目录(不填则默认)', '成品自动转移至成品库'], optional: true },
  ],
  推送配置: [
    { title: '推送总控', icon: Send, desc: '开播/关播通知开关与检测频率',
      keys: ['直播状态推送渠道', '开播推送开启(是/否)', '关播推送开启(是/否)',
             '直播推送检测频率(秒)', '只推送通知不录制(是/否)'] },
    { title: '通用内容模板', icon: BellRing, desc: '所有渠道共用的推送文案模板',
      keys: ['自定义推送标题', '自定义开播推送内容', '自定义关播推送内容'] },
    { title: '钉钉 / 微信 / Bark / Ntfy / PushPlus', icon: Send,
      keys: ['钉钉推送接口链接', '钉钉通知@对象(填手机号)', '钉钉通知@全体(是/否)',
             '微信推送接口链接', 'bark推送接口链接', 'bark推送中断级别', 'bark推送铃声',
             'ntfy推送地址', 'ntfy推送标签', 'ntfy推送邮箱', 'pushplus推送token'] },
    { title: 'Telegram', icon: Send, keys: ['tgapi令牌', 'tg聊天id(个人或者群组id)'] },
    { title: '邮件 SMTP', icon: Send,
      keys: ['smtp邮件服务器', 'smtp邮件服务器端口', '是否使用smtp服务ssl加密(是/否)',
             '邮箱登录账号', '发件人密码(授权码)', '发件人邮箱', '发件人显示昵称', '收件人邮箱'] },
  ],
  账号密码: [
    { title: '登录型平台账号', icon: KeyRound, desc: '以下平台录制需登录态，填写账号密码后自动获取/刷新 Cookie',
      keys: [] },   // 兜底：账号密码 tab 全部进这一节
  ],
  Cookie: [
    { title: '平台 Cookie / Token', icon: Cookie, desc: '各平台录制所需 Cookie。留空则用默认；录制报错风控时可在此更新',
      keys: [] },   // 兜底
  ],
  其他: [
    { title: '其他', icon: Wrench, keys: [] },
  ],
}

// 配置项中文说明 & 友好名（key 冒号后 → 显示/提示）
const META = {
  '原画|超清|高清|标清|流畅': { label: '默认录制画质', tip: '原画最高清，越往后越省流量' },
  '是否去除名称中的表情符号': { label: '去除文件名表情', tip: '主播昵称里的 emoji 不写进文件名' },
  '是否使用代理ip(是/否)': { label: '启用代理（总开关）', tip: '设为「是」才允许下面的平台名单走代理；「否」则全部直连' },
  '代理地址': { label: '代理地址', tip: '格式 http://ip:port 或 socks5://ip:port，如 http://127.0.0.1:7890' },
  '使用代理录制的平台(逗号分隔)': { label: '走代理的平台名单', tip: '逗号分隔，平台名或 URL 子串命中即走代理。如 tiktok, twitch, youtube' },
  '额外使用代理录制的平台(逗号分隔)': { label: '额外走代理的平台', tip: '补充名单，在上一项之外再追加走代理的平台' },
  '是否跳过代理检测(是/否)': { label: '跳过代理连通性检测', tip: '录制前不做代理可用性预检（跳过更快，但代理失效时会录失败）' },
  '缓存目录(不填则默认)': { label: '缓存库目录', tip: '下载缓存库根目录，留空默认 cache/' },
  '成品目录(不填则默认)': { label: '成品库目录', tip: '最终 mp4 存放目录，留空默认 downloads/' },
  '成品自动转移至成品库': { label: '成品自动转移', tip: '是：录完自动移到成品库；否：留在缓存目录' },
  '保存文件夹是否以作者区分': { label: '按主播建子目录', tip: '每个主播一个文件夹' },
  '保存文件夹是否以时间区分': { label: '按时间建子目录', tip: '每次录制按日期再分子目录' },
  '保存文件夹是否以标题区分': { label: '按直播标题建子目录', tip: '以直播标题作为子目录名' },
  '保存文件名是否包含标题': { label: '文件名含标题', tip: '文件名加直播标题' },
  '视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频': { label: '分片格式（兜底默认）', tip: '未指定流类型对应格式时的默认容器' },
  'HLS流分片格式': { label: 'HLS 流分片格式', tip: '拉 m3u8 流录制时用的容器：ts 最稳，mkv/mp4 也可' },
  'FLV流分片格式': { label: 'FLV 流分片格式', tip: '拉 flv 流录制时用的容器：flv 最低延迟' },
  'Agora流分片格式': { label: 'Agora 流分片格式', tip: 'RTC/声网类流录制容器（预留）' },
  '分段录制是否开启': { label: '开启分段录制', tip: '按分段时间切片，最终仍合并成整段 mp4' },
  '视频分段时间(秒)': { label: '分片时长（秒）', tip: '单个 ts 分片时长，默认 1800（30 分钟）' },
  '单次录制最大时长(秒)': { label: '单次录制时长上限（秒）', tip: '录满这么久自动生成一个成品 mp4 并继续录下一个；0 = 不限。默认 3600（1 小时）' },
  '单次录制最大大小(mb)': { label: '单次录制大小上限（MB）', tip: '录满这么大自动封顶生成成品；0 = 不限' },
  '录制完成后自动转为mp4格式': { label: '录完合并为 mp4', tip: '是：把分片合并成一个完整 mp4 成品' },
  'mp4格式重新编码为h264': { label: 'mp4 编码为 H.264', tip: '否=直接封装（快、无损）；是=重编码 H.264（兼容性最好、慢）' },
  '追加格式后删除原文件': { label: '转码后删原文件', tip: '合并/转码成功后删掉中间 ts 分片' },
  '生成时间字幕文件': { label: '生成时间字幕', tip: '为录制生成 .srt 时间轴字幕' },
  '是否录制完成后执行自定义脚本': { label: '录完执行自定义脚本', tip: '是：成品后运行下面的命令' },
  '自定义脚本执行命令': { label: '自定义脚本命令', tip: '如 python /path/x.py，录制完成后调用' },
  '同一时间访问网络的线程数': { label: '并发线程数', tip: '同时探测/访问的网络线程上限' },
  '循环时间(秒)': { label: '循环探测间隔（秒）', tip: '每隔多久检查一次主播是否开播' },
  '排队读取网址时间(秒)': { label: '排队错峰（秒）', tip: '多房间启动的错峰间隔' },
  '是否显示循环秒数': { label: '日志显示循环秒', tip: '调试用' },
  '是否显示直播源地址': { label: '日志显示直播源', tip: '调试用，打印真实流地址' },
  '录制空间剩余阈值(gb)': { label: '磁盘剩余告警阈值（GB）', tip: '剩余空间低于此值告警/停录' },
  '是否强制启用https录制': { label: '强制 https 录制', tip: '把 http 流地址提升为 https' },
  '直播状态推送渠道': { label: '推送渠道', tip: '可多填：微信|钉钉|tg|邮箱|bark|ntfy|pushplus' },
  '开播推送开启(是/否)': { label: '开播推送', tip: '主播开播时通知' },
  '关播推送开启(是/否)': { label: '关播推送', tip: '主播下播时通知' },
  '直播推送检测频率(秒)': { label: '推送检测频率（秒）', tip: '多久检测一次状态变化' },
  '只推送通知不录制(是/否)': { label: '只通知不录制', tip: '开启后只发通知，不实际录制' },
  '自定义推送标题': { label: '推送标题模板', tip: '支持占位符，如 主播名' },
  '自定义开播推送内容': { label: '开播推送内容', tip: '开播通知正文模板' },
  '自定义关播推送内容': { label: '关播推送内容', tip: '关播通知正文模板' },
  'ntfy推送地址': { label: 'ntfy 地址', tip: '如 https://ntfy.sh/你的主题' },
  'ntfy推送标签': { label: 'ntfy 标签', tip: '通知表情标签' },
  'ntfy推送邮箱': { label: 'ntfy 邮箱', tip: '可选' },
  'pushplus推送token': { label: 'PushPlus token', tip: 'pushplus.plus 的 token' },
  'bark推送接口链接': { label: 'Bark 地址', tip: 'Bark App 推送地址' },
  'bark推送中断级别': { label: 'Bark 中断级别', tip: 'active / timeSensitive / passive' },
  'bark推送铃声': { label: 'Bark 铃声', tip: '通知铃声名' },
  '微信推送接口链接': { label: '微信推送链接', tip: 'Server酱等微信推送 Webhook' },
  '钉钉推送接口链接': { label: '钉钉机器人 Webhook', tip: '钉钉群机器人地址' },
  '钉钉通知@对象(填手机号)': { label: '钉钉 @手机号', tip: '多人用逗号分隔' },
  '钉钉通知@全体(是/否)': { label: '钉钉 @全体', tip: '是=@所有人' },
  'tgapi令牌': { label: 'Telegram Bot Token', tip: 'BotFather 给的 token' },
  'tg聊天id(个人或者群组id)': { label: 'Telegram 聊天 ID', tip: '接收推送的 chat_id' },
  'smtp邮件服务器': { label: 'SMTP 服务器', tip: '如 smtp.qq.com' },
  'smtp邮件服务器端口': { label: 'SMTP 端口', tip: '如 465 / 587' },
  '是否使用smtp服务ssl加密(是/否)': { label: 'SMTP SSL 加密', tip: '是=SSL 连接（465 端口通常要开）' },
  '邮箱登录账号': { label: '发件邮箱账号', tip: 'SMTP 登录用户名' },
  '发件人密码(授权码)': { label: '发件密码/授权码', tip: '邮箱 SMTP 授权码，非登录密码' },
  '发件人邮箱': { label: '发件人地址', tip: 'From 地址' },
  '发件人显示昵称': { label: '发件人昵称', tip: '收件方看到的发件人名称' },
  '收件人邮箱': { label: '收件人地址', tip: '接收通知的邮箱，多个用逗号分隔' },
  'partner_code': { label: 'PopkonTV 合作方码', tip: '默认 P-00001' },
  'twitcasting账号类型': { label: 'TwitCasting 账号类型', tip: 'normal / 其他' },
}

function groupName(key) {
  const i = key.indexOf(':')
  const head = i > 0 ? key.slice(0, i) : '其他'
  for (const t of TABS) { if (t.match.some(m => head.includes(m))) return t.name }
  return '其他'
}
function shortKey(key) { const i = key.indexOf(':'); return i > 0 ? key.slice(i + 1) : key }
function labelOf(key) { return META[shortKey(key)]?.label || shortKey(key) }
function tipOf(key) { return META[shortKey(key)]?.tip || '' }
// Cookie tab 平台名美化
function platformName(key) {
  let k = shortKey(key).replace(/_(cookie|token)$/i, '').replace(/_/g, ' ')
  return k
}

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return k ? all.value.filter(c => c.key.toLowerCase().includes(k) || labelOf(c.key).toLowerCase().includes(k)) : all.value
})
const pageTitle = computed(() => props.onlyGroup ? (TABS.find(t => t.name === props.onlyGroup)?.title || '设置') : '系统配置')
const pageSub = computed(() => {
  if (props.onlyGroup === '录制设置') return '整体录制参数 · 画质 / 保存 / 分段 / 转码 / 目录 / 网络 · 修改即时生效'
  if (props.onlyGroup === '推送配置') return '消息推送 · 开播关播通知 / 各渠道配置 · 修改即时生效'
  return '分类管理全部配置 · 修改后即时生效（无需重启）'
})
const activeTabObj = computed(() => TABS.find(t => t.name === activeTab.value) || TABS[0])
const activeTabTitle = computed(() => activeTabObj.value.title)
const isCookieTab = computed(() => activeTab.value === 'Cookie')

// 平台名单类字段移到「平台管理」页逐平台设置，这里不再展示（数据保留在 DB）
const HIDDEN_KEYS = new Set(['使用代理录制的平台(逗号分隔)', '额外使用代理录制的平台(逗号分隔)'])
function countOf(name) { return all.value.filter(c => groupName(c.key) === name && !HIDDEN_KEYS.has(shortKey(c.key))).length }
const totalCount = computed(() => props.onlyGroup ? countOf(props.onlyGroup) : all.value.length)

// 当前 tab 的项，按 SECTION_RULES 分到各小节；未命中的进兜底小节
const sections = computed(() => {
  const tabName = activeTab.value
  const tabFiltered = filtered.value.filter(c => groupName(c.key) === tabName && !HIDDEN_KEYS.has(shortKey(c.key)))
  if (!tabFiltered.length) return []
  const rules = SECTION_RULES[tabName] || []
  const used = new Set()
  const out = []
  for (const rule of rules) {
    const items = tabFiltered.filter(c => {
      const sk = shortKey(c.key)
      return rule.keys.length === 0
        ? !used.has(c.key) && (rule.__fallback ? true : false)
        : rule.keys.includes(sk) && !used.has(c.key)
    })
    // 兜底小节（keys 为空）承接本 tab 所有还没被别的规则认领的项
    let finalItems = items
    if (rule.keys.length === 0) {
      finalItems = tabFiltered.filter(c => !used.has(c.key))
    }
    finalItems.forEach(c => used.add(c.key))
    if (finalItems.length) out.push({ ...rule, items: finalItems })
  }
  // 剩余没被任何规则认领的项 → 归入"更多设置"
  const rest = tabFiltered.filter(c => !used.has(c.key))
  if (rest.length) out.push({ title: '更多设置', icon: Wrench, items: rest })
  return out
})
const flatCount = computed(() => sections.value.reduce((a, s) => a + s.items.length, 0))

function onTab(name) { activeTab.value = name; kw.value = '' }

function isSecret(key) { return /cookie|token|password|pass|secret|api[_-]?key|accesstoken|密码|授权码/i.test(key) }
function masked(c) {
  if (!isSecret(c.key)) return trunc(c.value)
  const v = String(c.value || '')
  return v.length > 8 ? v.slice(0, 4) + '••••' + v.slice(-4) : '••••••'
}
function trunc(v) {
  if (v == null) return ''
  const s = String(v)
  return s.length > 300 ? s.slice(0, 300) + '…' : s
}

// 控件类型判定
const BOOL_KEYS = new Set([
  'mp4格式重新编码为h264','保存文件名是否包含标题','保存文件夹是否以作者区分',
  '保存文件夹是否以时间区分','保存文件夹是否以标题区分','分段录制是否开启',
  '录制完成后自动转为mp4格式','是否使用代理ip(是/否)','是否去除名称中的表情符号',
  '是否强制启用https录制','是否录制完成后执行自定义脚本','是否显示循环秒数',
  '是否显示直播源地址','是否跳过代理检测(是/否)','生成时间字幕文件','追加格式后删除原文件',
  '成品自动转移至成品库','关播推送开启(是/否)','只推送通知不录制(是/否)','开播推送开启(是/否)',
  '是否使用smtp服务ssl加密(是/否)','钉钉通知@全体(是/否)',
])
// 枚举型：短名 → 选项列表
const SELECT_OPTS = {
  '原画|超清|高清|标清|流畅': ['原画','超清','高清','标清','流畅'],
  '视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频': ['ts','mkv','flv','mp4','mp3音频','m4a音频'],
  'HLS流分片格式': ['ts','mkv','mp4'],
  'FLV流分片格式': ['flv','ts','mp4'],
  'Agora流分片格式': ['ts','mkv','mp4'],
  'bark推送中断级别': ['active','timeSensitive','passive'],
  'twitcasting账号类型': ['normal','其他'],
}
const PLATFORM_KEYS = new Set(['使用代理录制的平台(逗号分隔)', '额外使用代理录制的平台(逗号分隔)'])
function fieldType(key) {
  const sk = shortKey(key)
  if (BOOL_KEYS.has(sk) || sk.endsWith('(是/否)')) return 'bool'
  if (PLATFORM_KEYS.has(sk)) return 'platforms'
  if (SELECT_OPTS[sk]) return 'select'
  return 'text'
}
function isProxyAddr(key) { return shortKey(key) === '代理地址' }
// 各字段的填写提示（无障碍 + 新手友好）
function placeholderOf(key) {
  const sk = shortKey(key)
  if (sk === '代理地址') return '如 http://127.0.0.1:7890 或 socks5://user:pass@host:port'
  if (sk === '循环时间(秒)') return '探测间隔秒数，如 300'
  if (sk === '视频分段时间(秒)') return '每片秒数，如 1800'
  if (sk === '单次录制最大时长(秒)') return '0=不限'
  if (sk === '单次录制最大大小(mb)') return '0=不限'
  if (isSecret(key) && !drafts.value[key]) return '（未设置）'
  return '（空）'
}
// 字段下方灰色提示（仅关键项给，保持简洁）
function hintOf(key) {
  const sk = shortKey(key)
  if (sk === '代理地址') return '支持 http:// 与 socks5:// ；仅「走代理的平台」命中时会使用'
  if (sk === '使用代理录制的平台(逗号分隔)') return '点选左侧标签添加；命中的平台直播地址才走代理，其余直连'
  return ''
}
function optionsFor(key) {
  const opts = SELECT_OPTS[shortKey(key)] || []
  return opts.map(o => ({ label: o, value: o }))
}

// 打开小节弹窗
function openSec(sec) { editSec.value = sec }
// 关闭（有未保存改动时用自定义弹层确认，避免误丢）
const showDiscard = ref(false)
function closeSec() {
  if (editSec.value && secDirty(editSec.value)) {
    showDiscard.value = true
    return
  }
  editSec.value = null
}
function confirmDiscard() {
  showDiscard.value = false
  editSec.value = null
}
function cancelDiscard() { showDiscard.value = false }
// 保存弹窗内小节
async function saveEditSec() {
  if (!editSec.value) return
  await saveSection(editSec.value)
  editSec.value = null
}
// 列表行是否有未保存改动
function secHasDirty(sec) { return secDirty(sec) }

// 某小节是否有未保存的改动
function secDirty(sec) {
  return sec.items.some(c => (drafts.value[c.key] ?? c.value ?? '') !== (c.value ?? ''))
}
// 保存整节：只提交有改动的项
async function saveSection(sec) {
  const dirty = sec.items.filter(c => (drafts.value[c.key] ?? c.value ?? '') !== (c.value ?? ''))
  if (!dirty.length) return
  let okCount = 0
  for (const c of dirty) {
    const val = drafts.value[c.key] ?? ''
    try {
      await api.setConfig(c.key, val)
      c.value = val
      c.updated_at = new Date().toISOString()
      okCount++
    } catch (e) { toast.err(labelOf(c.key) + '：' + e.message) }
  }
  if (okCount) toast.ok(`已保存 ${sec.title} · ${okCount} 项`)
}

function syncDrafts() {
  const d = {}
  for (const c of all.value) d[c.key] = c.value ?? ''
  drafts.value = d
}

onMounted(async () => {
  try { all.value = await api.listConfigs(); syncDrafts() }
  catch (e) { toast.err(e.message) }
})
</script>

<style scoped>
.tabs {
  display: flex; gap: 6px; margin-bottom: 18px; flex-wrap: wrap;
  border-bottom: 1px solid var(--border-soft);
}
.tab {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 10px 16px; border: none; background: transparent; cursor: pointer;
  color: var(--dim); font-size: 13.5px; font-weight: 500;
  border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.15s, border-color 0.15s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-count { font-size: 11px; padding: 1px 7px; border-radius: 10px; background: var(--panel-2); color: var(--dim); font-weight: 600; }
.tab.active .tab-count { background: var(--accent-soft); color: var(--accent); }

.filter-bar { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; }
.hint { font-size: 12px; color: var(--dim); }

.sec-ic { color: var(--accent); }

/* 紧凑小节列表：一行一个小节 */
.sec-list { display: flex; flex-direction: column; gap: 8px; }
.sec-row {
  display: flex; align-items: center; gap: 14px; width: 100%;
  padding: 14px 18px; border-radius: var(--radius);
  background: var(--panel); border: 1px solid var(--border);
  cursor: pointer; text-align: left; transition: border-color .15s, background .15s;
  color: var(--text); font: inherit;
}
.sec-row:hover { border-color: var(--accent); background: var(--panel-2); }
.sec-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sec-ic-box {
  display: inline-flex; align-items: center; justify-content: center;
  width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0;
  background: var(--accent-soft); color: var(--accent);
}
.sec-main { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.sec-title { font-size: 14px; font-weight: 600; }
.sec-count { font-size: 12px; color: var(--dim); padding: 2px 9px; border-radius: 10px; background: var(--panel-2); flex-shrink: 0; }
.sec-dirty-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--amber,#f5a623); flex-shrink: 0; }
.sec-arrow { color: var(--dim); flex-shrink: 0; }

/* 编辑弹窗 */
.cfg-modal { width: 720px; max-width: 92vw; max-height: 84vh; display: flex; flex-direction: column; }
.cfg-modal .modal-body { flex: 1; overflow-y: auto; }
.cfg-grid { display: flex; flex-direction: column; }
.cfg-row { display: flex; gap: 16px; padding: 12px 2px; border-bottom: 1px solid var(--border-soft); align-items: flex-start; }
.cfg-row:last-child { border-bottom: none; }
.cfg-label-cell { width: 200px; flex-shrink: 0; padding-top: 6px; }
.cfg-input-cell { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-end; }
.cfg-ctrl { width: fit-content; max-width: 100%; display: flex; justify-content: flex-end; }
.cfg-ctrl.is-wide { width: 100%; }
.cfg-ctrl.is-wide .input { width: 100%; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
.cfg-ctrl .switch-right { margin-left: auto; }
.cfg-ctrl .dd { width: auto; }
.cfg-input-cell .field-hint { width: fit-content; max-width: 100%; text-align: right; }

.cfg-label { font-weight: 500; color: var(--text); font-size: 13px; }
.cell-input { width: auto; min-width: 2ch; height: 32px; padding: 0 10px; font-size: 12.5px; box-sizing: border-box; max-width: 100%; }
.field-hint { margin-top: 5px; font-size: 11.5px; color: var(--dim); line-height: 1.4; }
</style>
