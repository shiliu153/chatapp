import { defineConfig, devices } from '@playwright/test'

// 默认 4173。Windows 上 4173 可能落在 Hyper-V 保留的端口段里(本地报 EACCES),
// 这时用 `PLAYWRIGHT_PORT=5000 npm run e2e` 换一个端口;CI 不需要设置。
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 4173)

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  fullyParallel: false, // 场景之间有账号与配对状态依赖,串行更稳
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
