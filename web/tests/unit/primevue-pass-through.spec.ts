import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { emberPassThrough } from '@/styles/primevue-pass-through'

/**
 * PrimeVue pass-through 的「只引用变量」门禁(E-3.2)。
 *
 * 为什么必须有它:pt 里写的是内联样式,值一旦是写死的色值/尺寸,它就绕过了整条
 * token 链路 —— `[data-theme='dark']` 覆盖不到、对比度门禁量不到、改
 * `design/tokens/*.json` 也改不动它,而且**没有任何报错**。
 *
 * 判据两条:
 * 1. 每个声明值必须是**单个** `var(--…)`(复合表达式的值要先在 CSS 里定义成变量);
 * 2. 被引用的变量必须真的存在于 `src/styles/tokens.generated.css`
 *    (防手写变量名错字 —— 错字在浏览器里静默失效,只有这条会红)。
 */
const generated = readFileSync(resolve(process.cwd(), 'src/styles/tokens.generated.css'), 'utf8')

/** 生成物里声明过的所有变量名(带 --)。 */
const declared = new Set([...generated.matchAll(/(--[\w-]+):/g)].map((m) => m[1]))

interface PartStyle {
  style: Record<string, string>
}

/** 收集 pt 里所有内联声明,带 `组件.part.属性` 的路径,失败时能直接定位。 */
function declarations(): { path: string; value: string }[] {
  const out: { path: string; value: string }[] = []
  for (const [component, parts] of Object.entries(emberPassThrough)) {
    for (const [part, options] of Object.entries(parts as Record<string, unknown>)) {
      const style = (options as PartStyle | undefined)?.style
      if (!style) continue
      for (const [property, value] of Object.entries(style)) {
        out.push({ path: `${component}.${part}.${property}`, value: String(value) })
      }
    }
  }
  return out
}

describe('PrimeVue pt:只引用 token 变量', () => {
  it('至少映射了 8 个组件(spec §8.2 的常态组件)', () => {
    expect(Object.keys(emberPassThrough).length).toBeGreaterThanOrEqual(8)
  })

  it('每个声明值都是单个 var(--…)', () => {
    const all = declarations()
    expect(all.length).toBeGreaterThan(20) // 防结构改动后空跑通过
    const offenders = all
      .filter(({ value }) => !/^var\(--[\w-]+\)$/.test(value))
      .map(({ path, value }) => `${path}: ${value}`)
    expect(offenders, `pt 里只能写 var(--…) ,以下不是:\n${offenders.join('\n')}`).toEqual([])
  })

  it('引用的变量都在 tokens.generated.css 里声明过', () => {
    const missing = declarations()
      .map(({ path, value }) => ({
        path,
        ref: /^var\((--[\w-]+)\)$/.exec(value)?.[1] ?? '',
      }))
      .filter(({ ref }) => !declared.has(ref))
      .map(({ path, ref }) => `${path} → ${ref}`)
    expect(missing, `这些变量生成物里没有(错字?):\n${missing.join('\n')}`).toEqual([])
  })
})
