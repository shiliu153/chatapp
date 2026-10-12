import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Page } from '@playwright/test'

/** 1×1 PNG(测试用照片,免去往仓库塞二进制)。 */
const PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

export function fixturePhoto(): string {
  const path = join(tmpdir(), `hb-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}.png`)
  writeFileSync(path, Buffer.from(PNG_BASE64, 'base64'))
  return path
}

/** 用手机号 + 开发期固定验证码登录(未注册自动建号)。 */
export async function login(page: Page, phone: string): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('手机号').fill(phone)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.getByPlaceholder('6 位验证码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()
}

/** 走完「完善资料」:昵称/性别/生日/城市 + 一张照片。 */
export async function completeProfile(page: Page, nickname: string): Promise<void> {
  await page.getByPlaceholder('昵称').fill(nickname)
  await page.getByRole('button', { name: '女生' }).click()
  await page.locator('input[type="date"]').fill('2000-01-01')
  await page.getByPlaceholder('城市').fill('上海')
  await page.locator('input[type="file"]').setInputFiles(fixturePhoto())
  await page.getByRole('button', { name: '开始使用' }).click()
}

/** 每次运行用不同号段,避免历史数据(划过/配对)干扰。 */
export function freshPhone(suffix: number): string {
  const tail = String(Date.now()).slice(-6)
  return `139${tail}${suffix}`
}
