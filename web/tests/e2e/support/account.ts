import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, type Page } from '@playwright/test'

/** 1×1 PNG(测试用照片,免去往仓库塞二进制)。 */
const PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

export function fixturePhoto(): string {
  const path = join(tmpdir(), `hb-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}.png`)
  writeFileSync(path, Buffer.from(PNG_BASE64, 'base64'))
  return path
}

/**
 * 关掉首启的协议弹窗(每个新 context 都是干净 localStorage,必然出现)。
 * 不处理的话它会盖住登录表单,`fill` 会一直等不到可交互的元素。
 */
export async function acceptLegalGate(page: Page): Promise<void> {
  const gate = page.locator('.legal-gate')
  if ((await gate.count()) === 0) return
  await gate.locator('input[type="checkbox"]').check()
  await gate.locator('.legal-gate__submit').click()
  await expect(gate).toHaveCount(0)
}

/** 用手机号 + 开发期固定验证码登录(未注册自动建号)。 */
export async function login(page: Page, phone: string): Promise<void> {
  await page.goto('/login')
  await acceptLegalGate(page)
  await page.getByPlaceholder('手机号').fill(phone)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.getByPlaceholder('6 位验证码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()
}

/**
 * 走完「完善资料」:昵称/性别/生日/城市/简介 + 一张照片。
 *
 * 简介不能漏 —— 后端的完善判定是 nickname/gender/birthday/city/bio + ≥1 张过审照片
 * (`users/models.py::missing_fields`),漏一项资料就是 incomplete,永远不会进别人的候选卡,
 * 主干流程会在「滑卡」那一步卡死。
 *
 * `city` 由调用方给:主干流程用它把双方候选池收窄到「只有对方」(候选池是随机序)。
 */
export async function completeProfile(
  page: Page,
  nickname: string,
  city = '上海',
): Promise<void> {
  await page.getByPlaceholder('昵称').fill(nickname)
  await page.getByRole('button', { name: '女生' }).click()
  await page.locator('input[type="date"]').fill('2000-01-01')
  await page.getByPlaceholder('城市').fill(city)
  await page.getByPlaceholder('一句话介绍自己').fill('很高兴认识你')

  // 先传照片并等它真的回来(徽标出现),否则提交时资料仍缺 photos
  await page.locator('.photo-grid__input').setInputFiles(fixturePhoto())
  await expect(page.locator('.photo-grid__badge')).toHaveCount(1, { timeout: 15_000 })

  await page.getByRole('button', { name: '开始使用' }).click()
  await page.waitForURL('**/home/discovery', { timeout: 15_000 })
}

/**
 * 每次运行用不同号段,避免历史数据(划过/配对)干扰。
 *
 * 必须是 **11 位**:后端 `accounts/serializers.py::PHONE_RE` 卡的是 `^1[3-9]\d{9}$`,
 * 计划原文的 `139 + 6 位 + 1 位` 只有 10 位,发验证码就会被 400 拒掉。
 */
export function freshPhone(suffix: number): string {
  const tail = String(Date.now()).slice(-7) // 后 7 位,保证时间不同则号码不同
  return `139${tail}${suffix}`
}
