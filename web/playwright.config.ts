import { defineConfig, devices } from '@playwright/test'

// 默认 4173。Windows 上 4173 可能落在 Hyper-V 保留的端口段里(本地报 EACCES),
// 这时用 `PLAYWRIGHT_PORT=5000 npm run e2e` 换一个端口;CI 不需要设置。
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 4173)
// preview 必须显式绑 127.0.0.1:vite preview 默认 host 是 `localhost`,在部分 Linux
// 环境(localhost 先解析到 ::1)只监听 IPv6,而 Playwright 轮询的是 127.0.0.1 →
// webServer 一直等到超时(E-3 首次 CI 就是这么红的)。
const HOST = '127.0.0.1'
// CI 里先单独 `npm run build`,再由 webServer 只起 preview:把构建失败与
// 「服务起不来」两类错误分开,也避免构建时间被算进 webServer 的超时窗口。
const SKIP_BUILD = process.env.PW_SKIP_BUILD === '1'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  fullyParallel: false, // 场景之间有账号与配对状态依赖,串行更稳
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://${HOST}:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: SKIP_BUILD
      ? `npm run preview -- --host ${HOST} --port ${PORT} --strictPort`
      : `npm run build && npm run preview -- --host ${HOST} --port ${PORT} --strictPort`,
    url: `http://${HOST}:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
