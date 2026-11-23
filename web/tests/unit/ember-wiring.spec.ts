import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 接线层门禁(E-3):兼容层与 Tailwind `@theme` 都不许自己造值。
 *
 * - `src/styles/ember-compat.css`(过渡期别名)只能从生成物派生;
 * - `src/styles/tailwind.css` 的 `@theme inline` 只能转发生成物里已有的变量。
 *
 * 判据三条,都是"错了不会报错、只会静默失效"的那类:
 * 1. 引用的变量必须存在(错字 → 浏览器里静默无效);
 * 2. 不许出现裸色值(`#hex` / `rgb(…)` / `hsl(…)`,含 `color-mix` 里的写法);
 * 3. 不许覆盖生成物已声明的变量名(同名会让生成物失效,且暗色块对不上)。
 */
const generated = readFileSync(resolve(process.cwd(), 'src/styles/tokens.generated.css'), 'utf8')
const compat = readFileSync(resolve(process.cwd(), 'src/styles/ember-compat.css'), 'utf8')
const tailwind = readFileSync(resolve(process.cwd(), 'src/styles/tailwind.css'), 'utf8')

/** 生成物里声明过的变量名(带 --)。 */
const generatedNames = new Set([...generated.matchAll(/(--[\w-]+):/g)].map((m) => m[1]))

/** 去掉 CSS 注释(注释里会引用变量名与色值,不能当代码判)。 */
const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '')

interface Declaration {
  name: string
  value: string
}

/** 取 `--name: value;` 形式的声明(单行,足够覆盖本项目的写法)。 */
function declarations(src: string): Declaration[] {
  return [...stripComments(src).matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(([, name, value]) => ({
    name,
    value: value.trim(),
  }))
}

describe('兼容层 ember-compat.css', () => {
  const decls = declarations(compat)
  const compatNames = new Set(decls.map((d) => d.name))

  it('别名数量符合预期(防文件被清空后空跑通过)', () => {
    expect(decls.length).toBeGreaterThan(50)
  })

  it('引用的变量都存在(生成物或本文件先声明过)', () => {
    const defined = new Set([...generatedNames, ...compatNames])
    const missing = decls.flatMap(({ name, value }) =>
      [...value.matchAll(/var\((--[\w-]+)\)/g)]
        .map((m) => m[1])
        .filter((ref) => !defined.has(ref))
        .map((ref) => `${name} → ${ref}`),
    )
    expect(missing, `引用了不存在的变量:\n${missing.join('\n')}`).toEqual([])
  })

  it('不写裸色值(只能由 color-mix / var() 派生)', () => {
    // 注意 `color-mix(in srgb, …)` 里的 srgb 不是 rgb(),所以正则要求 rgb/ hsl 后有左括号
    const offenders = decls
      .filter(({ value }) => /#[0-9a-fA-F]{3,8}\b/.test(value) || /\b(rgb|rgba|hsl|hsla)\(/i.test(value))
      .map(({ name, value }) => `${name}: ${value}`)
    expect(offenders, `兼容层里不许出现裸色值:\n${offenders.join('\n')}`).toEqual([])
  })

  it('不覆盖生成物里的变量名(同名会让生成物失效)', () => {
    const shadowed = decls.filter((d) => generatedNames.has(d.name)).map((d) => d.name)
    expect(shadowed, `这些名字生成物里已有,兼容层不许重定义:\n${shadowed.join('\n')}`).toEqual([])
  })
})

describe('Tailwind @theme 转发', () => {
  const themeBlock = /@theme inline \{([\s\S]*?)\n\}/.exec(stripComments(tailwind))?.[1] ?? ''
  const forwards = declarations(themeBlock)

  it('至少转发了 30 条语义 token(防空跑)', () => {
    expect(forwards.length).toBeGreaterThanOrEqual(30)
  })

  it('全部是 `var(--生成物变量)` 的纯转发', () => {
    const offenders = forwards
      .filter(({ value }) => !/^var\(--[\w-]+\)$/.test(value))
      .map(({ name, value }) => `${name}: ${value}`)
    expect(offenders, `@theme 里只许转发变量:\n${offenders.join('\n')}`).toEqual([])
  })

  it('转发目标必须存在于 tokens.generated.css', () => {
    const missing = forwards
      .map(({ name, value }) => ({
        name,
        ref: /^var\((--[\w-]+)\)$/.exec(value)?.[1] ?? '',
      }))
      .filter(({ ref }) => !generatedNames.has(ref))
      .map(({ name, ref }) => `${name} → ${ref}`)
    expect(missing, `转发到了不存在的变量:\n${missing.join('\n')}`).toEqual([])
  })

  it('没有引入 preflight(E-3 不重排存量页面)', () => {
    expect(stripComments(tailwind)).not.toContain('preflight.css')
  })
})
