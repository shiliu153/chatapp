import { expect, test } from '@playwright/test'
import { completeProfile, freshPhone, login } from './support/account'

/**
 * CI 冒烟 e2e（backlog E-3）：只覆盖「注册登录 → 完善资料 → 发现页 / 广场页能拉到列表」。
 *
 * 为什么不跑全量：`main-flow` / `edge-cases` 需要 imserver + Celery（发消息、灰条、已读回执、
 * 图片/语音上传），在 GitHub Actions 里起全栈的收益抵不过 flaky 风险。全量 8 条仍按
 * `npm run e2e` 在本地/测试环境人工跑；这条轨只要求 MySQL + Redis + Django + Web preview，
 * 目标是「登录与两个核心列表在每次 PR 都被真后端验证一遍」。
 */
test('冒烟：注册登录 → 完善资料 → 发现页与消息页能拉到', async ({ page }) => {
  const phone = freshPhone(7)

  // 1) 新手机号登录（开发模式固定验证码 123456），新账号进完善资料页
  await login(page, phone)
  await page.waitForURL('**/onboarding', { timeout: 15_000 })

  // 2) 完善资料（含上传一张照片；CI 里 AUTO_APPROVE=1，提交后立刻过审）
  await completeProfile(page, '冒烟用户', '上海')
  await expect(page).toHaveURL(/\/home\/discovery/)

  // 3) 发现页：真后端拉候选。CI 空库里没有别人 → 空态；本地有数据 → 有卡。两者都算通过。
  await expect(page.locator('.candidate-card, .app-empty').first()).toBeVisible({
    timeout: 15_000,
  })

  // 4) 广场页：拉 /posts 列表（这一步验证 Django 列表接口）。
  //    不用消息页 —— 会话列表走 imserver 的 /im/api/conversations，冒烟轨不起 imserver。
  await page.goto('/home/square')
  await expect(page.locator('.post-card, .app-empty').first()).toBeVisible({ timeout: 15_000 })
})
