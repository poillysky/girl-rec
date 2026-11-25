import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '总览' } },
  { path: '/rooms', name: 'rooms', component: () => import('../views/Rooms.vue'), meta: { title: '直播间' } },
  { path: '/live', name: 'live', component: () => import('../views/Live.vue'), meta: { title: '实时监控' } },
  { path: '/recordings', name: 'recordings', component: () => import('../views/Recordings.vue'), meta: { title: '文件管理' } },
  { path: '/settings/rec', name: 'rec-settings', component: () => import('../views/RecSettings.vue'), meta: { title: '录制设置' } },
  { path: '/platforms', name: 'platforms', component: () => import('../views/Platforms.vue'), meta: { title: '平台管理' } },
  { path: '/settings/push', name: 'push-settings', component: () => import('../views/PushSettings.vue'), meta: { title: '推送设置' } },
  { path: '/configs', redirect: '/settings/rec' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} · GirlRec` : 'GirlRec'
})

export default router