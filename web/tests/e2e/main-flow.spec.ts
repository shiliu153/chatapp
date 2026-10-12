import { expect, test, type Page } from '@playwright/test'
import { completeProfile, fixturePhoto, freshPhone, login } from './support/account'

/**
 * 主干流程:注册 → 互滑配对 → 聊天(文本 + 图片)→ 广场发布/评论 → 拉黑。
 *
 * 与计划原文的四处偏差(执行时实测修正,理由写在各自注释里):
 *  1. 候选池是 `order_by("?")` 且线上有 20+ 个已完善账号,**第一张卡不一定是对方**
 *     → 用「偏好城市 = 本用例专属城市」把候选池收窄到 1 人(见 narrowDeckTo)。
 *  2. 手机号必须 11 位(后端 PHONE_RE),计划原文的拼法只有 10 位 → 已在 account.ts 修。
 *  3. 完善资料必须填「简介」,否则资料永远是 incomplete、不会进对方候选 → 已在 account.ts 修。
 *  4. 首启协议弹窗会盖住登录表单 → 已在 account.ts 的 login() 里处理。
 */
test('主干流程:注册 → 配对 → 聊天 → 广场 → 拉黑', async ({ browser }) => {
  const phoneA = freshPhone(1)
  const phoneB = freshPhone(2)
  // 两个人用同一个专属城市,就能把彼此的候选池收窄到「只有对方」
  const city = `测试城${String(Date.now()).slice(-6)}`

  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const pageA = await contextA.newPage()
  const pageB = await contextB.newPage()

  // 1) 两个账号各自登录并完善资料
  await login(pageA, phoneA)
  await completeProfile(pageA, '阿泽', city)
  await login(pageB, phoneB)
  await completeProfile(pageB, '小雨', city)

  // 2) 双方都设「想找的城市 = 专属城市」→ 候选池里只剩对方,避免随机序干扰
  await narrowDeckTo(pageA, city)
  await narrowDeckTo(pageB, city)

  // 3) B 先喜欢 A(第一刀不配对),A 再喜欢 B → 配对成功
  await pageB.goto('/home/discovery')
  await expect(pageB.locator('.candidate-card__name')).toHaveText('阿泽', { timeout: 15_000 })
  await pageB.locator('.swipe-deck__like').click()
  await expect(pageB.locator('.match-moment')).toHaveCount(0) // 单向喜欢还不算配对

  await pageA.goto('/home/discovery')
  await expect(pageA.locator('.candidate-card__name')).toHaveText('小雨', { timeout: 15_000 })
  await pageA.locator('.swipe-deck__like').click()
  await expect(pageA.locator('.match-moment')).toBeVisible()
  await expect(pageA.locator('.match-moment__title')).toHaveText('你们互相喜欢')

  // 4) 从配对情感时刻进聊天并发一条文本
  await pageA.locator('.match-moment__chat').click()
  await expect(pageA.locator('.chat__title')).toHaveText('小雨', { timeout: 15_000 })
  await pageA.getByPlaceholder('说点什么…').fill('你好呀')
  await pageA.locator('.chat__send').click()
  await expect(pageA.locator('.message-bubble').last()).toContainText('你好呀')

  // 5) B 在消息页看到会话,点进去能收到
  await pageB.goto('/home/chats')
  await expect(pageB.locator('.chats__name').first()).toHaveText('阿泽', { timeout: 15_000 })
  await pageB.locator('.chats__row').first().click()
  await expect(pageB.locator('.message-bubble').last()).toContainText('你好呀', { timeout: 15_000 })

  // 6) 发图片(走 IM 上传,慢一点)
  await pageB.locator('.chat__picker').setInputFiles(fixturePhoto())
  await expect(pageB.locator('.message-image__img').last()).toBeVisible({ timeout: 30_000 })

  // 7) 广场:发一条动态
  await pageA.goto('/home/square')
  await pageA.getByRole('button', { name: '发动态' }).click()
  await pageA.locator('.post-compose__text').fill('第一条动态')
  await pageA.locator('.post-compose__submit').click()
  await expect(pageA.locator('.post-card').first()).toContainText('第一条动态', { timeout: 15_000 })

  // 8) 进 B 的资料页拉黑(B 发过动态才好在广场点到;B 此刻还没发,直接用 URL)
  await pageA.goto(`/users/${await userIdOf(pageB)}`)
  await expect(pageA.locator('.user-profile__name')).toHaveText('小雨', { timeout: 15_000 })
  pageA.on('dialog', (d) => d.accept()) // 拉黑要二次确认
  await pageA.locator('.user-profile__block').click()
  await expect(pageA.locator('.user-profile__notice')).toHaveText('已拉黑')

  await contextA.close()
  await contextB.close()
})

/** 把「想找的城市」设成专属城市,让候选池只剩对方(候选池是随机序,不能假设第一张就是对方)。 */
async function narrowDeckTo(page: Page, city: string): Promise<void> {
  await page.goto('/preference')
  await page.getByPlaceholder('想找的城市(留空=不限)').fill(city)
  await page.locator('.preference__submit').click()
  await expect(page.locator('.preference__saved')).toHaveText('已保存')
}

/** 读当前登录账号的 user_id(localStorage 里就有,省一次接口)。 */
async function userIdOf(page: Page): Promise<number> {
  const id = await page.evaluate(() => localStorage.getItem('hb.userId'))
  if (!id) throw new Error('没读到 hb.userId,登录态可能没建立')
  return Number(id)
}
