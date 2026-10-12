import { expect, test } from '@playwright/test'
import { acceptLegalGate, completeProfile, freshPhone, login } from './support/account'

/**
 * 边界场景(对应 spec §16 / 计划三 Task 9.4)。
 *
 * 与计划原文的偏差:
 *  - 「未同意协议时首启弹窗出现」原本先 goto('/login') 再清 localStorage 再 reload,
 *    但弹窗是**挂载时**读 localStorage 的(`LegalGate.vue` 的 `ref(!isAgreed())`),
 *    清完必须重新加载才看得到 —— 改成直接用一个干净的 context 打开(更贴近真实首访)。
 *  - 「中文渲染」原本要求 innerText.length > 200,而 `privacyText` 只有 25 行/约 400 字符,
 *    jsdom 之外的 `<pre>` 里含换行;这里保留长度断言但用真实正文长度校验。
 */

test('深链直开与 F5 不 404', async ({ page }) => {
  const phone = freshPhone(3)
  await login(page, phone)
  await completeProfile(page, '深链')

  await page.goto('/home/square')
  await page.reload()
  await expect(page.locator('.square__title')).toBeVisible()

  await page.goto('/settings')
  await page.reload()
  await expect(page.locator('.settings__title')).toBeVisible()
})

test('中文渲染正常(不是空白也不是方块)', async ({ page }) => {
  await page.goto('/legal/privacy')
  await acceptLegalGate(page)
  await expect(page.locator('.legal__title')).toHaveText('隐私政策')
  const text = await page.locator('.legal__body').innerText()
  expect(text).toMatch(/[\u4e00-\u9fa5]/) // 含中文
  expect(text).toContain('本政策说明') // 真的是正文,不是空壳
  expect(text.length).toBeGreaterThan(200)
})

test('窗口拖窄仍是 PC 壳层(不是移动端引导页)', async ({ page }) => {
  const phone = freshPhone(4)
  await login(page, phone)
  await completeProfile(page, '窄窗')

  await page.setViewportSize({ width: 700, height: 800 })
  await page.goto('/home/discovery')
  await expect(page.locator('.app-sidebar')).toBeVisible()
  await expect(page.getByText('请在电脑上打开网页版')).toHaveCount(0)
})

test('移动端 UA 进引导页,下载按钮为敬请期待', async ({ browser }) => {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
    viewport: { width: 390, height: 844 },
  })
  const page = await context.newPage()
  await page.goto('/home/discovery')

  await expect(page.getByText('请在电脑上打开网页版')).toBeVisible()
  await expect(page.getByRole('button', { name: /敬请期待/ })).toBeDisabled()
  await context.close()
})

test('未同意协议时首启弹窗出现', async ({ browser }) => {
  // 全新 context = 干净 localStorage,等价于「第一次访问」
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')

  await expect(page.locator('.legal-gate')).toBeVisible()
  await expect(page.locator('.legal-gate__title')).toHaveText('欢迎来到心跳')

  // 不勾选直接提交 → 提示而不是放行
  await page.locator('.legal-gate__submit').click()
  await expect(page.locator('.legal-gate__hint')).toHaveText('请先阅读并同意以下文件')

  // 勾选后关掉,且刷新不再出现(版本号已记在本地)
  await page.locator('.legal-gate input[type="checkbox"]').check()
  await page.locator('.legal-gate__submit').click()
  await expect(page.locator('.legal-gate')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.legal-gate')).toHaveCount(0)
  await context.close()
})

test('第二个标签页登录不会把第一个标签页登出(同端多实例分流)', async ({ context, page }) => {
  const phone = freshPhone(5)
  await login(page, phone)
  await completeProfile(page, '多标签')
  await expect(page.locator('.app-sidebar')).toBeVisible()

  const second = await context.newPage() // 同一 context = 共享 localStorage
  await second.goto('/home/chats')
  await second.waitForTimeout(3_000)

  // 第一个标签页仍应处于登录态:地址栏没有跳回 /login,也没有被顶号浮层
  await expect(page.locator('.kicked-overlay')).toHaveCount(0)
  expect(new URL(page.url()).pathname).not.toBe('/login')
  await second.close()
})
