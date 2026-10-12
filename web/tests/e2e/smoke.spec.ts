import { expect, test } from '@playwright/test'

test('首屏能打开且是中文界面', async ({ page }) => {
  await page.goto('/login')
  // 用角色 + exact 定位:首启弹窗里也有「欢迎来到心跳」,纯 getByText('心跳') 会撞上两个元素
  await expect(page.getByRole('heading', { name: '心跳', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
})
