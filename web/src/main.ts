/**
 * 样式底座(E-3 起)。顺序即层叠顺序,自上而下:
 *
 * 1. `tokens.generated.css` —— 「余烬 Ember」生成物(`design/tokens/*.json` →
 *    `scripts/design_tokens.py`),**唯一的事实来源,禁手改**。
 * 2. `ember-compat.css` —— 过渡期兼容层:存量页面还在用「心跳」的变量名
 *    (`--color-text1` / `--space-md` …),这里把它们映射到 Ember 语义 token。
 *    E-5 逐页迁移完即删。
 * 3. `base.css` —— 全局重置、@font-face、焦点圈。
 * 4. `tailwind.css` —— `@theme inline` 把 token 转发成语义工具类(`bg-surface-card` 等),
 *    供 E-5 起的新页面使用;不引 preflight(见该文件头注释)。
 */
import './styles/tokens.generated.css'
import './styles/ember-compat.css'
import './styles/base.css'
import './styles/tailwind.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import App from './App.vue'
import { router } from './router'
import { installClientErrorReporting } from './api/clientErrors'
import ForceUpdate from './features/app/ForceUpdate.vue'
import { APP_VERSION } from './features/settings/appInfo'
import { isOutdated } from './features/app/version'
import { applyStoredTheme } from './stores/theme'
import { emberPassThrough } from './styles/primevue-pass-through'

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
  // PrimeVue 只做无样式模式:组件行为/键盘/ARIA 由它负责,视觉全部来自 pt 里的 CSS 变量
  // (`src/styles/primevue-pass-through.ts`)。这里不注册任何组件 —— E-5 逐页迁移时
  // 按需 `import Button from 'primevue/button'`,避免把整包打进产物。
  app
    .use(createPinia())
    .use(router)
    .use(PrimeVue, { unstyled: true, pt: emberPassThrough })
    .mount('#app')
}

void bootstrap()
