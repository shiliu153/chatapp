import './styles/tokens.css'
import './styles/base.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { installClientErrorReporting } from './api/clientErrors'
import ForceUpdate from './features/app/ForceUpdate.vue'
import { APP_VERSION } from './features/settings/appInfo'
import { isOutdated } from './features/app/version'
import { applyStoredTheme } from './stores/theme'

// 外观:在 createApp 之前就把 data-theme 写上,深色用户首屏不会先闪一下白
applyStoredTheme()

interface AppConfig {
  min_app_version: string
  latest_version: string
  download_url: string
}

/** 前端未捕获异常上报(开关见 .env.* 的 VITE_ERROR_REPORTING,本地/测试默认关)。 */
const errorReporter = installClientErrorReporting({ appVersion: APP_VERSION })

async function bootstrap(): Promise<void> {
  let config: AppConfig | null = null
  try {
    const response = await fetch('/api/v1/app/config')
    if (response.ok) config = (await response.json()) as AppConfig
  } catch {
    // 网络抖动不阻断启动
  }
  if (config && isOutdated(APP_VERSION, config.min_app_version)) {
    createApp(ForceUpdate, {
      current: APP_VERSION,
      min: config.min_app_version,
      downloadUrl: config.download_url,
    }).mount('#app')
    return
  }
  const app = createApp(App)
  // 组件渲染/生命周期里的异常不会触发 window.onerror,只能靠 Vue 自己的钩子
  app.config.errorHandler = (error, _instance, info) => {
    errorReporter.report(error, { stack: error instanceof Error ? error.stack : info })
    console.error(error)
  }
  app.use(createPinia()).use(router).mount('#app')
}

void bootstrap()
