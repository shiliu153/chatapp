import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, type Page } from '@playwright/test'

/**
 * 「token 真的接线了」的端到端证明(E-3.1)。
 *
 * 为什么需要它:CSS 变量写错名字**不会报错**,只会静默失效 —— 页面上那块颜色变成
 * 透明/继承色,而所有单元测试与类型检查照样绿。这条断言从生成物里读出
 * `surface.page` 的值,再和浏览器算出来的 `body` 背景色比一次,把
 * 「design/tokens → tokens.generated.css → ember-compat.css → base.css」这条链路
 * 真正跑通一遍。
 *
 * 取 `body` 而不是某个业务元素:页面视觉会在 E-5 逐页重排,但「body 底 = 页面底」
 * 是这套 token 里唯一不会变的一条。
 */

/** `#FBF7F3` / `#FBF7F3FF` → `rgb(251, 247, 243)`(浏览器 getComputedStyle 的写法)。 */
function hexToRgb(hex: string): string {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return `rgb(${r}, ${g}, ${b})`
}

/** 从生成物里取某个变量的字面值(只取 `:root` 那一块,暗色块不会混进来)。 */
export function generatedToken(name: string): string {
  const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.generated.css'), 'utf8')
  const rootBlock = /:root \{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(rootBlock)
  if (!match) throw new Error(`tokens.generated.css 的 :root 里没有 --${name}`)
  return match[1].trim()
}

/** 断言页面底色与生成物里的 `surface.page` 一致(= 变量真的解析到了)。 */
export async function expectTokensWired(page: Page): Promise<void> {
  const expected = hexToRgb(generatedToken('color-surface-page'))
  await expect(page.locator('body')).toHaveCSS('background-color', expected)
}
