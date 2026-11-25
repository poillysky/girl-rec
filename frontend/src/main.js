import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'   // 全局设计系统令牌与组件类

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')