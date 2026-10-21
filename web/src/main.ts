import './styles/tokens.css'
import './styles/base.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import ForceUpdate from './features/app/ForceUpdate.vue'
import { APP_VERSION } from './features/settings/appInfo'
import { isOutdated } from './features/app/version'

interface AppConfig {
  min_app_version: string
  latest_version: string
  download_url: string
}

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
  createApp(App).use(createPinia()).use(router).mount('#app')
}

void bootstrap()
