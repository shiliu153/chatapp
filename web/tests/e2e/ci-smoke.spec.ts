import { expect, test } from '@playwright/test'
import { acceptLegalGate, completeProfile, freshPhone, login } from './support/account'
import { expectNoCriticalA11y } from './support/a11y'
import { expectTokensWired } from './support/tokens'

/**
 * CI 冒烟 e2e（backlog E-3）：只覆盖「注册登录 → 完善资料 → 发现页 / 广场页能拉到列表」。
 *
 * 为什么不跑全量：`main-flow` / `edge-cases` 需要 imserver + Celery（发消息、灰条、已读回执、
 * 图片/语音上传），在 GitHub Actions 里起全栈的收益抵不过 flaky 风险。全量 8 条仍按
 * `npm run e2e` 在本地/测试环境人工跑；这条轨只要求 MySQL + Redis + Django + Web preview，
 * 目标是「登录与两个核心列表在每次 PR 都被真后端验证一遍」。
 *
 * E-3.3 起这条冒烟同时是**无障碍门禁**：主流程四个页面（登录 / 完善资料 / 发现 / 广场）
 * 各跑一次 axe，零 critical（判据与理由见 `support/a11y.ts`）。之所以放在 e2e 而不是
 * 组件测试里：axe 的多数规则要靠真实布局与真实 DOM，jsdom 里量不到。
 */
test('冒烟：注册登录 → 完善资料 → 发现页与消息页能拉到', async ({ page }) => {
  const phone = freshPhone(7)

  // 0) 先单独开一次登录页,只为在「表单已渲染、协议弹窗已关」的状态下扫无障碍:
  //    login() 里会重新 goto('/login'),协议弹窗已记在 localStorage,不会再挡路
  await page.goto('/login')
  await acceptLegalGate(page)
  await expect(page.getByPlaceholder('手机号')).toBeVisible()
  // 生成物 → 兼容层 → base.css 这条链路在这一刻必须已经生效(变量名写错不会报错)
  await expectTokensWired(page)
  await expectNoCriticalA11y(page, '登录页')

  // 1) 新手机号登录（开发模式固定验证码 123456），新账号进完善资料页
  await login(page, phone)
  await page.waitForURL('**/onboarding', { timeout: 15_000 })
  await expectNoCriticalA11y(page, '完善资料页')

  // 2) 完善资料（含上传一张照片；CI 里 AUTO_APPROVE=1，提交后立刻过审）
  await completeProfile(page, '冒烟用户', '上海')
  await expect(page).toHaveURL(/\/home\/discovery/)

  // 3) 发现页：真后端拉候选。CI 空库里没有别人 → 空态；本地有数据 → 有卡。两者都算通过。
  await expect(page.locator('.candidate-card, .app-empty').first()).toBeVisible({
    timeout: 15_000,
  })
  await expectNoCriticalA11y(page, '发现页')

  // 4) 广场页：拉 /posts 列表（这一步验证 Django 列表接口）。
  //    不用消息页 —— 会话列表走 imserver 的 /im/api/conversations，冒烟轨不起 imserver。
  await page.goto('/home/square')
  await expect(page.locator('.post-card, .app-empty').first()).toBeVisible({ timeout: 15_000 })
  await expectNoCriticalA11y(page, '广场页')
})
