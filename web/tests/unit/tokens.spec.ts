import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 样式底座的存在性断言(E-3)。
 *
 * 这里**曾经**是「心跳 token:Web 与 App 数值必须一致」的双份比对:E-2 / E-3 合并前,
 * `web/src/styles/tokens.css` 是手抄的一份,`app/lib/core/theme/*.dart` 是另一份,
 * 这条用例逐字段比对两者,防止抄歪。
 *
 * E-3 之后链路只剩一条 —— `design/tokens/*.json` → 生成物 —— 双份比对的前提消失
 * (`web/src/styles/tokens.css` 已删除),这条旧规则本身作废。取而代之的是下面两条
 * 轻量断言:生成物在,且带的是 Ember 的品牌 token。真正"值对不对"由 `contract` 轨的
 * 三道门禁负责(`design_tokens.py --check` / `design_contrast.py --check` /
 * `design_spec_sync.py --check`),不在这里重复一遍阈值。
 *
 * 工作目录固定是 `web/`(vitest 的 root),所以用 `process.cwd()` 而不是 `import.meta.url`。
 */
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.generated.css'), 'utf8')

describe('token 生成物(E-3 起为单一事实来源)', () => {
  it('生成物存在且带 Ember 的品牌色变量', () => {
    expect(css).toContain('--color-brand-default')
    // 生成物头部有「禁止手改」的横幅:它同时是判据 —— 生成器改产物名字时这条会红,
    // 提醒去同步 src/main.ts 的引入顺序与 compat 层的映射
    expect(css).toContain('GENERATED CODE - DO NOT EDIT BY HAND')
  })

  it('明暗两套语义色键集一致(暗色少一个就会静默回落到浅色)', () => {
    // 与 contract 轨的 `design_tokens.py --check` 同口径的浅层复核:只数键、
    // 不判值(判值要解析 DTCG,那是生成器的活,这里重复一遍只会漂移)
    const light = /:root \{([\s\S]*?)\}/.exec(css)?.[1] ?? ''
    const dark = /\[data-theme="dark"\] \{([\s\S]*?)\}/.exec(css)?.[1] ?? ''
    const keys = (block: string) =>
      [...block.matchAll(/(--color-[\w-]+):/g)].map((m) => m[1]).sort()
    const lightKeys = keys(light)
    const darkKeys = keys(dark)
    expect(lightKeys.length).toBeGreaterThan(15)
    expect(darkKeys).toEqual(lightKeys)
  })
})
